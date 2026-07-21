from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from ..constants import EXCLUDED_PROJECT
from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..db import dict_rows, get_connection, get_db_path, now_str
from ..path_utils import normalize_path_key
from ..resources.title_parsing import normalize_file_name
from ..write_gate import DATABASE_WRITE_GATE
from . import folder_index_state_repository

if TYPE_CHECKING:
    from ..worker_health import WorkerHealthReporter

INDEX_STATUS_PENDING = "pending"
INDEX_STATUS_INDEXING = "indexing"
INDEX_STATUS_READY = "ready"
INDEX_STATUS_STALE = "stale"
INDEX_STATUS_ERROR = "error"

_SCAN_BATCH_SIZE = 250
_WORKER_IDLE_SECONDS = 5.0
_MISS_REFRESH_COOLDOWN_SECONDS = 60.0
_GC_PENDING_CODE = "folder_index_gc_pending"

_WORKER_WAKE_EVENT = threading.Event()
_MISS_REFRESH_TIMES: dict[tuple[str, int, bool], float] = {}


class FolderIndexScanError(RuntimeError):
    """Stable path-free failure proving a scan was incomplete."""

    def __init__(self, code: str) -> None:
        normalized = str(code or "folder_index_scan_incomplete")
        super().__init__(normalized)
        self.code = normalized


class FolderIndexScanInterrupted(FolderIndexScanError):
    def __init__(self) -> None:
        super().__init__("folder_index_scan_interrupted")


def request_rebuild_for_rule(rule_id: int) -> None:
    with get_connection() as conn:
        folder_index_state_repository.request_rebuild(conn, int(rule_id))
    wake_folder_index_worker()


def delete_index_for_rule(rule_id: int, *, conn=None) -> None:
    if conn is not None:
        folder_index_state_repository.delete_rule_index(conn, int(rule_id))
        return
    with get_connection() as own_conn:
        delete_index_for_rule(rule_id, conn=own_conn)


def _replacement_cache_identity() -> tuple[str, int]:
    database_key = str(get_db_path().resolve())
    with get_connection() as conn:
        replacement_epoch = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )
    return database_key, replacement_epoch


def request_refresh_for_enabled_rules(include_excluded: bool = False) -> None:
    database_key, replacement_epoch = _replacement_cache_identity()
    cache_key = (database_key, replacement_epoch, bool(include_excluded))
    current = time.monotonic()
    if current - _MISS_REFRESH_TIMES.get(cache_key, 0.0) < _MISS_REFRESH_COOLDOWN_SECONDS:
        return
    _MISS_REFRESH_TIMES[cache_key] = current
    project_clause = "" if include_excluded else "AND p.name <> ?"
    params: list[object] = [] if include_excluded else [EXCLUDED_PROJECT]
    with get_connection() as conn:
        rule_ids = [
            int(row["id"])
            for row in conn.execute(
                f"""
                SELECT fpr.id
                FROM folder_project_rule fpr
                JOIN project p ON p.id = fpr.project_id
                WHERE fpr.enabled = 1
                  AND p.enabled = 1
                  AND COALESCE(p.is_archived, 0) = 0
                  AND COALESCE(p.is_deleted, 0) = 0
                  {project_clause}
                """,
                params,
            ).fetchall()
        ]
    for rule_id in rule_ids:
        request_rebuild_for_rule(rule_id)


def ensure_index_states_for_folder_rules() -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO folder_rule_index_state(
                folder_rule_id, status, valid_from, active_generation,
                building_generation, build_status, last_error, file_count,
                error_message, refresh_requested, created_at, updated_at
            )
            SELECT fpr.id, ?, NULL, NULL, NULL, ?, NULL, 0, NULL, 1, ?, ?
            FROM folder_project_rule fpr
            WHERE NOT EXISTS (
                SELECT 1 FROM folder_rule_index_state state
                WHERE state.folder_rule_id = fpr.id
            )
            """,
            (
                INDEX_STATUS_PENDING,
                INDEX_STATUS_PENDING,
                timestamp,
                timestamp,
            ),
        )


def recover_interrupted_indexes() -> int:
    """Discard only unfinished builds, then retry superseded generation GC."""

    timestamp = now_str()
    active_generations: list[tuple[int, int]] = []
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        states = conn.execute(
            """
            SELECT folder_rule_id, active_generation, building_generation
            FROM folder_rule_index_state
            WHERE building_generation IS NOT NULL
               OR build_status = 'indexing'
               OR status = 'indexing'
            """
        ).fetchall()
        for state in states:
            rule_id = int(state["folder_rule_id"])
            active = int(state["active_generation"] or 0)
            building = int(state["building_generation"] or 0)
            if building > 0 and building != active:
                conn.execute(
                    """
                    DELETE FROM folder_rule_file_index
                    WHERE folder_rule_id = ? AND generation = ?
                    """,
                    (rule_id, building),
                )
            conn.execute(
                """
                UPDATE folder_rule_index_state
                SET status = CASE
                        WHEN active_generation IS NULL THEN 'pending'
                        ELSE 'ready' END,
                    building_generation = NULL,
                    build_status = CASE
                        WHEN active_generation IS NULL THEN 'pending'
                        ELSE 'ready' END,
                    refresh_requested = CASE
                        WHEN active_generation IS NULL THEN 1 ELSE 0 END,
                    last_error = CASE
                        WHEN active_generation IS NULL THEN NULL
                        ELSE last_error END,
                    error_message = CASE
                        WHEN active_generation IS NULL THEN NULL
                        ELSE error_message END,
                    updated_at = ?
                WHERE folder_rule_id = ?
                """,
                (timestamp, rule_id),
            )
            if active > 0:
                active_generations.append((rule_id, active))
        conn.commit()

    for rule_id, active in active_generations:
        try:
            _cleanup_old_generations(rule_id, active)
            _clear_gc_pending(rule_id, active)
        except Exception:
            _mark_gc_pending(rule_id, active)
    _retry_pending_gc()
    return len(states)


def rebuild_folder_index(
    rule_id: int,
    stop_event: threading.Event | None = None,
) -> bool:
    rule = _load_folder_rule(rule_id)
    if not rule:
        delete_index_for_rule(rule_id)
        return False
    folder_path = str(rule.get("folder_path") or "").strip()
    generation, started_at = _begin_generation(rule_id)
    if not folder_path or not Path(folder_path).is_dir():
        _fail_generation(rule_id, generation, "folder_index_root_unavailable")
        return False

    count = 0
    batch: list[tuple] = []
    try:
        for item in _iter_files(
            folder_path,
            bool(rule.get("recursive")),
            stop_event,
        ):
            batch.append(_entry_tuple(rule_id, generation, item, started_at))
            if len(batch) >= _SCAN_BATCH_SIZE:
                _insert_entry_batch(batch)
                count += len(batch)
                batch = []
                if stop_event is not None and stop_event.wait(0.01):
                    raise FolderIndexScanInterrupted()
        if batch:
            _insert_entry_batch(batch)
            count += len(batch)
        _activate_generation(rule_id, generation, started_at, count)
    except FolderIndexScanInterrupted:
        _abandon_generation(rule_id, generation)
        return False
    except FolderIndexScanError as exc:
        _fail_generation(rule_id, generation, exc.code)
        return False
    except Exception as exc:
        logging.warning(
            "folder index build failed rule=%s exception=%s",
            int(rule_id),
            type(exc).__name__,
        )
        _fail_generation(rule_id, generation, "folder_index_build_failed")
        return False

    # Activation has committed. New generation is authoritative regardless of
    # whether superseded rows can be reclaimed immediately.
    try:
        _cleanup_old_generations(rule_id, generation)
        _clear_gc_pending(rule_id, generation)
    except Exception as exc:
        logging.warning(
            "folder index generation GC deferred rule=%s exception=%s",
            int(rule_id),
            type(exc).__name__,
        )
        _mark_gc_pending(rule_id, generation)
    return True


def validate_ready_indexes(stop_event: threading.Event | None = None) -> None:
    with get_connection() as conn:
        states = dict_rows(
            conn.execute(
                """
                SELECT folder_rule_id
                FROM folder_rule_index_state
                WHERE active_generation IS NOT NULL
                ORDER BY folder_rule_id
                """
            ).fetchall()
        )
    for state in states:
        if stop_event is not None and stop_event.is_set():
            return
        _validate_rule_index(int(state["folder_rule_id"]), stop_event)


def mark_index_stale(rule_id: int, reason: str = "folder_index_stale") -> None:
    timestamp = now_str()
    code = _stable_error_code(reason, "folder_index_stale")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = ?, build_status = ?, last_error = ?,
                error_message = ?, refresh_requested = 1, updated_at = ?
            WHERE folder_rule_id = ?
            """,
            (
                INDEX_STATUS_STALE,
                INDEX_STATUS_STALE,
                code,
                code,
                timestamp,
                int(rule_id),
            ),
        )


def run_folder_index_worker(
    stop_event: threading.Event,
    *,
    health: "WorkerHealthReporter",
) -> None:
    """Run iterations only; AppRuntime owns thread started/stopped state."""

    logging.info("folder index worker loop enter")
    try:
        ensure_index_states_for_folder_rules()
        recover_interrupted_indexes()
        validate_ready_indexes(stop_event)
    except Exception:
        logging.exception("folder index startup validation failed")
        health.failed("folder_index_startup_failed")
    else:
        health.succeeded()
    while not stop_event.is_set():
        try:
            if DATABASE_WRITE_GATE.writes_blocked():
                health.maintenance_paused(True)
                _wait_for_worker()
                continue
            health.maintenance_paused(False)
            ensure_index_states_for_folder_rules()
            _retry_pending_gc()
            for rule_id in _pending_rule_ids():
                if stop_event.is_set() or DATABASE_WRITE_GATE.writes_blocked():
                    break
                rebuild_folder_index(rule_id, stop_event)
            health.succeeded()
            _wait_for_worker()
        except Exception:
            logging.exception("folder index worker error")
            health.failed("folder_index_iteration_failed")
            _wait_for_worker()
    logging.info("folder index worker loop exit")


def wake_folder_index_worker() -> None:
    _WORKER_WAKE_EVENT.set()


def _wait_for_worker() -> None:
    _WORKER_WAKE_EVENT.wait(_WORKER_IDLE_SECONDS)
    _WORKER_WAKE_EVENT.clear()


def _pending_rule_ids(limit: int = 20) -> list[int]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT folder_rule_id
            FROM folder_rule_index_state
            WHERE (refresh_requested = 1 OR build_status IN (?, ?))
              AND COALESCE(last_error, '') <> ?
            ORDER BY updated_at, folder_rule_id
            LIMIT ?
            """,
            (
                INDEX_STATUS_PENDING,
                INDEX_STATUS_STALE,
                _GC_PENDING_CODE,
                int(limit),
            ),
        ).fetchall()
    return [int(row["folder_rule_id"]) for row in rows]


def _load_folder_rule(rule_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM folder_project_rule WHERE id = ?",
            (int(rule_id),),
        ).fetchone()
    return dict(row) if row else None


def _begin_generation(rule_id: int) -> tuple[int, str]:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            """
            SELECT active_generation, building_generation
            FROM folder_rule_index_state
            WHERE folder_rule_id = ?
            """,
            (int(rule_id),),
        ).fetchone()
        maximum = conn.execute(
            """
            SELECT COALESCE(MAX(generation), 0) AS value
            FROM folder_rule_file_index
            WHERE folder_rule_id = ?
            """,
            (int(rule_id),),
        ).fetchone()
        generation = max(
            int(maximum["value"] or 0),
            int(state["active_generation"] or 0) if state else 0,
            int(state["building_generation"] or 0) if state else 0,
        ) + 1
        conn.execute(
            """
            INSERT INTO folder_rule_index_state(
                folder_rule_id, status, valid_from, active_generation,
                building_generation, build_status, last_error, file_count,
                error_message, refresh_requested, created_at, updated_at
            )
            VALUES (?, ?, NULL, NULL, ?, ?, NULL, 0, NULL, 0, ?, ?)
            ON CONFLICT(folder_rule_id) DO UPDATE SET
                status = CASE
                    WHEN folder_rule_index_state.active_generation IS NULL
                    THEN excluded.status ELSE folder_rule_index_state.status END,
                building_generation = excluded.building_generation,
                build_status = excluded.build_status,
                last_error = NULL,
                error_message = NULL,
                refresh_requested = 0,
                updated_at = excluded.updated_at
            """,
            (
                int(rule_id),
                INDEX_STATUS_INDEXING,
                generation,
                INDEX_STATUS_INDEXING,
                timestamp,
                timestamp,
            ),
        )
        conn.execute(
            """
            DELETE FROM folder_rule_file_index
            WHERE folder_rule_id = ? AND generation = ?
            """,
            (int(rule_id), generation),
        )
        conn.commit()
    return generation, timestamp


def _activate_generation(
    rule_id: int,
    generation: int,
    valid_from: str,
    file_count: int,
) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            actual = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS value
                    FROM folder_rule_file_index
                    WHERE folder_rule_id = ? AND generation = ?
                    """,
                    (int(rule_id), int(generation)),
                ).fetchone()["value"]
                or 0
            )
            if actual != int(file_count):
                raise ValueError("folder_index_generation_incomplete")
            cursor = conn.execute(
                """
                UPDATE folder_rule_index_state
                SET status = ?, valid_from = ?, active_generation = ?,
                    building_generation = NULL, build_status = ?, last_error = NULL,
                    last_indexed_at = ?, last_checked_at = ?, file_count = ?,
                    error_message = NULL, refresh_requested = 0, updated_at = ?
                WHERE folder_rule_id = ? AND building_generation = ?
                """,
                (
                    INDEX_STATUS_READY,
                    valid_from,
                    int(generation),
                    INDEX_STATUS_READY,
                    timestamp,
                    timestamp,
                    actual,
                    timestamp,
                    int(rule_id),
                    int(generation),
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("folder_index_generation_superseded")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                logging.warning("folder index activation rollback failed")
            raise


def _fail_generation(rule_id: int, generation: int, message: str) -> None:
    """Fail and delete only the generation still owned as BUILDING."""

    timestamp = now_str()
    code = _stable_error_code(message, "folder_index_build_failed")
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = CASE WHEN active_generation IS NULL THEN ? ELSE status END,
                building_generation = NULL, build_status = ?, last_error = ?,
                error_message = ?, refresh_requested = 0, updated_at = ?
            WHERE folder_rule_id = ? AND building_generation = ?
              AND COALESCE(active_generation, -1) <> ?
            """,
            (
                INDEX_STATUS_ERROR,
                INDEX_STATUS_ERROR,
                code,
                code,
                timestamp,
                int(rule_id),
                int(generation),
                int(generation),
            ),
        )
        if cursor.rowcount == 1:
            conn.execute(
                """
                DELETE FROM folder_rule_file_index
                WHERE folder_rule_id = ? AND generation = ?
                """,
                (int(rule_id), int(generation)),
            )
        conn.commit()


def _abandon_generation(rule_id: int, generation: int) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = CASE WHEN active_generation IS NULL THEN ? ELSE status END,
                building_generation = NULL, build_status = ?,
                refresh_requested = 1, updated_at = ?
            WHERE folder_rule_id = ? AND building_generation = ?
              AND COALESCE(active_generation, -1) <> ?
            """,
            (
                INDEX_STATUS_PENDING,
                INDEX_STATUS_PENDING,
                timestamp,
                int(rule_id),
                int(generation),
                int(generation),
            ),
        )
        if cursor.rowcount == 1:
            conn.execute(
                """
                DELETE FROM folder_rule_file_index
                WHERE folder_rule_id = ? AND generation = ?
                """,
                (int(rule_id), int(generation)),
            )
        conn.commit()


def _mark_gc_pending(rule_id: int, active_generation: int) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = ?, build_status = ?, last_error = ?,
                error_message = ?, refresh_requested = 0, updated_at = ?
            WHERE folder_rule_id = ? AND active_generation = ?
            """,
            (
                INDEX_STATUS_READY,
                INDEX_STATUS_READY,
                _GC_PENDING_CODE,
                _GC_PENDING_CODE,
                timestamp,
                int(rule_id),
                int(active_generation),
            ),
        )


def _clear_gc_pending(rule_id: int, active_generation: int) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET last_error = NULL, error_message = NULL, updated_at = ?
            WHERE folder_rule_id = ? AND active_generation = ?
              AND last_error = ?
            """,
            (
                timestamp,
                int(rule_id),
                int(active_generation),
                _GC_PENDING_CODE,
            ),
        )


def _retry_pending_gc(limit: int = 20) -> None:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT folder_rule_id, active_generation
            FROM folder_rule_index_state
            WHERE last_error = ? AND active_generation IS NOT NULL
            ORDER BY updated_at, folder_rule_id
            LIMIT ?
            """,
            (_GC_PENDING_CODE, int(limit)),
        ).fetchall()
    for row in rows:
        rule_id = int(row["folder_rule_id"])
        generation = int(row["active_generation"])
        try:
            _cleanup_old_generations(rule_id, generation)
            _clear_gc_pending(rule_id, generation)
        except Exception:
            logging.warning("folder index generation GC retry deferred rule=%s", rule_id)


def _cleanup_old_generations(rule_id: int, active_generation: int) -> None:
    while True:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id FROM folder_rule_file_index
                WHERE folder_rule_id = ? AND generation <> ?
                ORDER BY id LIMIT ?
                """,
                (int(rule_id), int(active_generation), _SCAN_BATCH_SIZE),
            ).fetchall()
            if not rows:
                return
            ids = [int(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"DELETE FROM folder_rule_file_index WHERE id IN ({placeholders})",
                ids,
            )


def _insert_entry_batch(batch: list[tuple]) -> None:
    if not batch:
        return
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO folder_rule_file_index(
                folder_rule_id, generation, file_name, normalized_file_name,
                file_path, normalized_path_key, mtime, size, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(folder_rule_id, generation, normalized_path_key)
            DO UPDATE SET
                file_name = excluded.file_name,
                normalized_file_name = excluded.normalized_file_name,
                file_path = excluded.file_path,
                mtime = excluded.mtime,
                size = excluded.size,
                updated_at = excluded.updated_at
            """,
            batch,
        )


def _entry_tuple(rule_id: int, generation: int, item: dict, timestamp: str) -> tuple:
    file_path = str(item["path"])
    file_name = str(item["name"])
    return (
        int(rule_id),
        int(generation),
        file_name,
        _normalize_index_file_name(file_name),
        file_path,
        normalize_path_key(file_path),
        item.get("mtime"),
        item.get("size"),
        timestamp,
        timestamp,
    )


def _iter_files(
    folder_path: str,
    recursive: bool,
    stop_event: threading.Event | None = None,
) -> Iterator[dict[str, object]]:
    root = folder_path
    stack = [folder_path]
    while stack:
        if stop_event is not None and stop_event.is_set():
            raise FolderIndexScanInterrupted()
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if stop_event is not None and stop_event.is_set():
                        raise FolderIndexScanInterrupted()
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if recursive:
                                stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        # A transiently removed entry was never part of a stable
                        # snapshot and can be omitted without claiming I/O success.
                        continue
                    except OSError as exc:
                        raise FolderIndexScanError(
                            "folder_index_entry_unreadable"
                        ) from exc
                    yield {
                        "name": entry.name,
                        "path": entry.path,
                        "mtime": float(stat.st_mtime),
                        "size": int(stat.st_size),
                    }
        except FolderIndexScanError:
            raise
        except FileNotFoundError as exc:
            code = (
                "folder_index_root_unavailable"
                if current == root
                else "folder_index_directory_disappeared"
            )
            raise FolderIndexScanError(code) from exc
        except OSError as exc:
            code = (
                "folder_index_root_unreadable"
                if current == root
                else "folder_index_directory_unreadable"
            )
            raise FolderIndexScanError(code) from exc


def _validate_rule_index(
    rule_id: int,
    stop_event: threading.Event | None = None,
) -> None:
    with get_connection() as conn:
        state = conn.execute(
            """
            SELECT active_generation, file_count
            FROM folder_rule_index_state WHERE folder_rule_id = ?
            """,
            (int(rule_id),),
        ).fetchone()
        generation = int(state["active_generation"] or 0) if state else 0
        expected_count = int(state["file_count"] or 0) if state else 0
        actual_count = (
            int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS value
                    FROM folder_rule_file_index
                    WHERE folder_rule_id = ? AND generation = ?
                    """,
                    (int(rule_id), generation),
                ).fetchone()["value"]
                or 0
            )
            if generation > 0
            else 0
        )
    if generation <= 0:
        return
    if actual_count != expected_count:
        mark_index_stale(rule_id, "folder_index_generation_count_mismatch")
        return

    last_id = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        with get_connection() as conn:
            rows = dict_rows(
                conn.execute(
                    """
                    SELECT id, file_path
                    FROM folder_rule_file_index
                    WHERE folder_rule_id = ? AND generation = ? AND id > ?
                    ORDER BY id LIMIT ?
                    """,
                    (int(rule_id), generation, last_id, _SCAN_BATCH_SIZE),
                ).fetchall()
            )
        if not rows:
            break
        for row in rows:
            last_id = int(row["id"])
            if not os.path.exists(str(row.get("file_path") or "")):
                mark_index_stale(rule_id, "folder_index_entry_missing")
                return
        if stop_event is not None:
            stop_event.wait(0.01)
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET last_checked_at = ?, updated_at = ?
            WHERE folder_rule_id = ? AND active_generation = ?
            """,
            (timestamp, timestamp, int(rule_id), generation),
        )


def _stable_error_code(value: str, default: str) -> str:
    normalized = str(value or "").strip()
    if normalized and len(normalized) <= 100 and all(
        character.isalnum() or character == "_" for character in normalized
    ):
        return normalized
    return default


def _normalize_index_file_name(file_name: str | None) -> str:
    value = str(file_name or "").strip()
    return normalize_file_name(value) if value else ""


__all__ = [
    "FolderIndexScanError",
    "FolderIndexScanInterrupted",
    "delete_index_for_rule",
    "ensure_index_states_for_folder_rules",
    "mark_index_stale",
    "rebuild_folder_index",
    "recover_interrupted_indexes",
    "request_rebuild_for_rule",
    "request_refresh_for_enabled_rules",
    "run_folder_index_worker",
    "validate_ready_indexes",
    "wake_folder_index_worker",
]
