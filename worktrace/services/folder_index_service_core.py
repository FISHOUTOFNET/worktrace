from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from ..constants import EXCLUDED_PROJECT
from ..db import dict_rows, get_connection, get_db_path, now_str
from ..path_utils import normalize_path_key
from ..resources.title_parsing import extract_file_name_from_title, normalize_file_name

INDEX_STATUS_PENDING = "pending"
INDEX_STATUS_INDEXING = "indexing"
INDEX_STATUS_READY = "ready"
INDEX_STATUS_STALE = "stale"
INDEX_STATUS_ERROR = "error"

_SCAN_BATCH_SIZE = 250
_WORKER_IDLE_SECONDS = 5.0
_MISS_REFRESH_COOLDOWN_SECONDS = 60.0

_WORKER_LOCK = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None
_MISS_REFRESH_TIMES: dict[tuple[str, bool], float] = {}


def request_rebuild_for_rule(rule_id: int) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO folder_rule_index_state(
                folder_rule_id, status, valid_from, active_generation,
                building_generation, build_status, last_error, file_count,
                error_message, refresh_requested, created_at, updated_at
            )
            VALUES (?, ?, NULL, NULL, NULL, ?, NULL, 0, NULL, 1, ?, ?)
            ON CONFLICT(folder_rule_id) DO UPDATE SET
                status = CASE
                    WHEN folder_rule_index_state.active_generation IS NULL
                    THEN excluded.status ELSE folder_rule_index_state.status END,
                build_status = excluded.build_status,
                building_generation = NULL,
                last_error = NULL,
                error_message = NULL,
                refresh_requested = 1,
                updated_at = excluded.updated_at
            """,
            (
                int(rule_id),
                INDEX_STATUS_PENDING,
                INDEX_STATUS_PENDING,
                timestamp,
                timestamp,
            ),
        )


def delete_index_for_rule(rule_id: int, *, conn=None) -> None:
    if conn is not None:
        conn.execute(
            "DELETE FROM folder_rule_file_index WHERE folder_rule_id = ?",
            (int(rule_id),),
        )
        conn.execute(
            "DELETE FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (int(rule_id),),
        )
        return
    with get_connection() as own_conn:
        delete_index_for_rule(rule_id, conn=own_conn)


def request_refresh_for_enabled_rules(include_excluded: bool = False) -> None:
    cache_key = (str(get_db_path().resolve()), bool(include_excluded))
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
        _fail_generation(rule_id, generation, f"folder not found: {folder_path}")
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
                    _abandon_generation(rule_id, generation)
                    return False
        if stop_event is not None and stop_event.is_set():
            _abandon_generation(rule_id, generation)
            return False
        if batch:
            _insert_entry_batch(batch)
            count += len(batch)
        _activate_generation(rule_id, generation, started_at, count)
        _cleanup_old_generations(rule_id, generation)
        return True
    except Exception as exc:
        logging.exception("folder index rebuild failed for rule %s", rule_id)
        _fail_generation(rule_id, generation, str(exc))
        return False


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


def lookup_indexed_paths_for_file_name(
    file_name: str | None,
    activity_start_time: str | None = None,
    *,
    include_excluded: bool = False,
    request_refresh_on_miss: bool = True,
    conn=None,
) -> list[dict]:
    normalized = _normalize_index_file_name(file_name)
    if not normalized:
        return []
    project_clause = "" if include_excluded else "AND p.name <> ?"
    time_clause = "AND state.valid_from <= ?" if activity_start_time else ""
    params: list[object] = [normalized]
    if not include_excluded:
        params.append(EXCLUDED_PROJECT)
    if activity_start_time:
        params.append(activity_start_time)
    sql = f"""
        SELECT idx.folder_rule_id, idx.file_name, idx.file_path,
               idx.normalized_path_key, state.valid_from, state.active_generation,
               fpr.folder_path, fpr.recursive, fpr.project_id,
               p.name AS project_name
        FROM folder_rule_file_index idx
        JOIN folder_rule_index_state state
          ON state.folder_rule_id = idx.folder_rule_id
         AND state.active_generation = idx.generation
        JOIN folder_project_rule fpr ON fpr.id = idx.folder_rule_id
        JOIN project p ON p.id = fpr.project_id
        WHERE idx.normalized_file_name = ?
          AND state.active_generation IS NOT NULL
          AND state.valid_from IS NOT NULL
          AND fpr.enabled = 1
          AND p.enabled = 1
          AND COALESCE(p.is_archived, 0) = 0
          AND COALESCE(p.is_deleted, 0) = 0
          {project_clause}
          {time_clause}
        ORDER BY length(fpr.normalized_folder_key) DESC, idx.id ASC
    """
    if conn is None:
        with get_connection() as read_conn:
            rows = dict_rows(read_conn.execute(sql, params).fetchall())
    else:
        rows = dict_rows(conn.execute(sql, params).fetchall())
    results: dict[str, dict] = {}
    stale_rule_ids: set[int] = set()
    for row in rows:
        path = str(row.get("file_path") or "").strip()
        key = str(row.get("normalized_path_key") or normalize_path_key(path))
        if not path or not os.path.exists(path):
            stale_rule_ids.add(int(row["folder_rule_id"]))
            continue
        results.setdefault(key, row)
    if conn is None:
        for stale_rule_id in stale_rule_ids:
            mark_index_stale(
                stale_rule_id,
                "indexed file path no longer exists",
            )
        if not results and not stale_rule_ids and request_refresh_on_miss:
            request_refresh_for_enabled_rules(include_excluded=include_excluded)
    return list(results.values())


def resolve_unique_path_from_title(
    window_title: str | None,
    activity_start_time: str | None = None,
    *,
    include_excluded: bool = True,
) -> str | None:
    file_name = extract_file_name_from_title(window_title)
    if not file_name:
        return None
    candidates = lookup_indexed_paths_for_file_name(
        file_name,
        activity_start_time,
        include_excluded=include_excluded,
    )
    if len(candidates) != 1:
        return None
    return str(candidates[0]["file_path"])


def find_matching_folder_rule_for_file_name(
    file_name: str | None,
    activity_start_time: str | None = None,
    *,
    conn=None,
) -> dict | None:
    candidates = lookup_indexed_paths_for_file_name(
        file_name,
        activity_start_time,
        include_excluded=False,
        request_refresh_on_miss=conn is None,
        conn=conn,
    )
    if not candidates:
        return None
    from . import folder_rule_service

    matched: dict[int, dict] = {}
    for candidate in candidates:
        rule = folder_rule_service.find_matching_folder_rule(
            str(candidate.get("file_path") or ""),
            conn=conn,
        )
        if rule:
            matched[int(rule["project_id"])] = rule
    if len(matched) != 1:
        return None
    return dict(next(iter(matched.values())))


def activity_matches_rule_by_index(activity: dict, rule_id: int) -> bool:
    file_name = _activity_file_name(activity)
    if not file_name:
        return False
    candidates = lookup_indexed_paths_for_file_name(
        file_name,
        str(activity.get("start_time") or "") or None,
        include_excluded=False,
    )
    if not candidates:
        return False
    from . import folder_rule_service

    project_ids: set[int] = set()
    for candidate in candidates:
        rule = folder_rule_service.find_matching_folder_rule(
            str(candidate.get("file_path") or "")
        )
        if rule:
            project_ids.add(int(rule["project_id"]))
    if len(project_ids) > 1:
        return False
    return any(
        int(candidate["folder_rule_id"]) == int(rule_id)
        for candidate in candidates
    )


def mark_index_stale(rule_id: int, reason: str = "") -> None:
    timestamp = now_str()
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
                reason[:500],
                reason[:500],
                timestamp,
                int(rule_id),
            ),
        )


def start_folder_index_worker(stop_event: threading.Event) -> threading.Thread | None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return _WORKER_THREAD
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop,
            args=(stop_event,),
            name="WorkTraceFolderIndex",
            daemon=True,
        )
        _WORKER_THREAD.start()
        return _WORKER_THREAD


def _worker_loop(stop_event: threading.Event) -> None:
    logging.info("folder index worker start")
    try:
        ensure_index_states_for_folder_rules()
        validate_ready_indexes(stop_event)
    except Exception:
        logging.exception("folder index startup validation failed")
    while not stop_event.is_set():
        try:
            from .secure_backup_service import is_secure_import_in_progress

            if is_secure_import_in_progress():
                stop_event.wait(_WORKER_IDLE_SECONDS)
                continue
            ensure_index_states_for_folder_rules()
            for rule_id in _pending_rule_ids():
                if stop_event.is_set() or is_secure_import_in_progress():
                    break
                rebuild_folder_index(rule_id, stop_event)
            stop_event.wait(_WORKER_IDLE_SECONDS)
        except Exception:
            logging.exception("folder index worker error")
            stop_event.wait(_WORKER_IDLE_SECONDS)
    logging.info("folder index worker stop")


def _pending_rule_ids(limit: int = 20) -> list[int]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT folder_rule_id
            FROM folder_rule_index_state
            WHERE refresh_requested = 1
               OR build_status IN (?, ?)
            ORDER BY updated_at, folder_rule_id
            LIMIT ?
            """,
            (INDEX_STATUS_PENDING, INDEX_STATUS_STALE, int(limit)),
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
            "DELETE FROM folder_rule_file_index WHERE folder_rule_id = ? AND generation = ?",
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


def _fail_generation(rule_id: int, generation: int, message: str) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM folder_rule_file_index WHERE folder_rule_id = ? AND generation = ?",
            (int(rule_id), int(generation)),
        )
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = CASE WHEN active_generation IS NULL THEN ? ELSE status END,
                building_generation = NULL, build_status = ?, last_error = ?,
                error_message = ?, refresh_requested = 0, updated_at = ?
            WHERE folder_rule_id = ? AND building_generation = ?
            """,
            (
                INDEX_STATUS_ERROR,
                INDEX_STATUS_ERROR,
                message[:500],
                message[:500],
                timestamp,
                int(rule_id),
                int(generation),
            ),
        )
        conn.commit()


def _abandon_generation(rule_id: int, generation: int) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM folder_rule_file_index WHERE folder_rule_id = ? AND generation = ?",
            (int(rule_id), int(generation)),
        )
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = CASE WHEN active_generation IS NULL THEN ? ELSE status END,
                building_generation = NULL, build_status = ?,
                refresh_requested = 1, updated_at = ?
            WHERE folder_rule_id = ? AND building_generation = ?
            """,
            (
                INDEX_STATUS_PENDING,
                INDEX_STATUS_PENDING,
                timestamp,
                int(rule_id),
                int(generation),
            ),
        )
        conn.commit()


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
):
    stack = [folder_path]
    while stack:
        if stop_event is not None and stop_event.is_set():
            return
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if stop_event is not None and stop_event.is_set():
                        return
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if recursive:
                                stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    yield {
                        "name": entry.name,
                        "path": entry.path,
                        "mtime": float(stat.st_mtime),
                        "size": int(stat.st_size),
                    }
        except OSError:
            continue


def _validate_rule_index(
    rule_id: int,
    stop_event: threading.Event | None = None,
) -> None:
    with get_connection() as conn:
        state = conn.execute(
            "SELECT active_generation FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (int(rule_id),),
        ).fetchone()
    generation = int(state["active_generation"] or 0) if state else 0
    if generation <= 0:
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
                mark_index_stale(rule_id, "indexed file path no longer exists")
                return
        if stop_event is not None:
            stop_event.wait(0.01)
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET last_checked_at = ?, updated_at = ?
            WHERE folder_rule_id = ?
            """,
            (timestamp, timestamp, int(rule_id)),
        )


def _activity_file_name(activity: dict) -> str | None:
    for value in (
        activity.get("resource_display_name"),
        activity.get("activity_display_name"),
        activity.get("window_title"),
    ):
        file_name = extract_file_name_from_title(str(value or ""))
        if file_name:
            return file_name
    return None


def _normalize_index_file_name(file_name: str | None) -> str:
    value = str(file_name or "").strip()
    return normalize_file_name(value) if value else ""
