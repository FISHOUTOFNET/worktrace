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
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO folder_rule_index_state(
                folder_rule_id, status, valid_from, file_count, error_message,
                refresh_requested, created_at, updated_at
            )
            VALUES (?, ?, NULL, 0, NULL, 1, ?, ?)
            ON CONFLICT(folder_rule_id) DO UPDATE SET
                status = excluded.status,
                valid_from = NULL,
                file_count = 0,
                error_message = NULL,
                refresh_requested = 1,
                updated_at = excluded.updated_at
            """,
            (int(rule_id), INDEX_STATUS_PENDING, ts, ts),
        )


def delete_index_for_rule(rule_id: int, *, conn=None) -> None:
    if conn is not None:
        conn.execute("DELETE FROM folder_rule_file_index WHERE folder_rule_id = ?", (int(rule_id),))
        conn.execute("DELETE FROM folder_rule_index_state WHERE folder_rule_id = ?", (int(rule_id),))
        return
    with get_connection() as conn:
        delete_index_for_rule(rule_id, conn=conn)


def request_refresh_for_enabled_rules(include_excluded: bool = False) -> None:
    cache_key = (str(get_db_path().resolve()), bool(include_excluded))
    now = time.monotonic()
    if now - _MISS_REFRESH_TIMES.get(cache_key, 0.0) < _MISS_REFRESH_COOLDOWN_SECONDS:
        return
    _MISS_REFRESH_TIMES[cache_key] = now

    ts = now_str()
    project_clause = "" if include_excluded else "AND p.name <> ?"
    params: list = []
    if not include_excluded:
        params.append(EXCLUDED_PROJECT)
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
            conn.execute(
                """
                INSERT INTO folder_rule_index_state(
                    folder_rule_id, status, valid_from, file_count, error_message,
                    refresh_requested, created_at, updated_at
                )
                VALUES (?, ?, NULL, 0, NULL, 1, ?, ?)
                ON CONFLICT(folder_rule_id) DO UPDATE SET
                    refresh_requested = 1,
                    error_message = NULL,
                    updated_at = excluded.updated_at
                """,
                (rule_id, INDEX_STATUS_PENDING, ts, ts),
            )


def ensure_index_states_for_folder_rules() -> None:
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO folder_rule_index_state(
                folder_rule_id, status, valid_from, file_count, error_message,
                refresh_requested, created_at, updated_at
            )
            SELECT fpr.id, ?, NULL, 0, NULL, 1, ?, ?
            FROM folder_project_rule fpr
            WHERE NOT EXISTS (
                SELECT 1
                FROM folder_rule_index_state state
                WHERE state.folder_rule_id = fpr.id
            )
            """,
            (INDEX_STATUS_PENDING, ts, ts),
        )


def rebuild_folder_index(rule_id: int, stop_event: threading.Event | None = None) -> bool:
    rule = _load_folder_rule(rule_id)
    if not rule:
        delete_index_for_rule(rule_id)
        return False

    folder_path = str(rule["folder_path"] or "").strip()
    start_ts = now_str()
    _set_indexing(rule_id, start_ts)
    if not folder_path or not Path(folder_path).is_dir():
        _mark_error(rule_id, f"folder not found: {folder_path}")
        return False

    try:
        _clear_entries(rule_id)
        file_count = 0
        batch: list[tuple] = []
        for item in _iter_files(folder_path, bool(rule["recursive"]), stop_event):
            batch.append(_entry_tuple(rule_id, item, start_ts))
            if len(batch) >= _SCAN_BATCH_SIZE:
                _insert_entry_batch(batch)
                file_count += len(batch)
                batch = []
                if stop_event is not None and stop_event.wait(0.01):
                    _mark_pending(rule_id)
                    return False
        if batch:
            _insert_entry_batch(batch)
            file_count += len(batch)
        _mark_ready(rule_id, start_ts, file_count)
        return True
    except Exception as exc:
        logging.exception("folder index rebuild failed for rule %s", rule_id)
        _mark_error(rule_id, str(exc))
        return False


def validate_ready_indexes(stop_event: threading.Event | None = None) -> None:
    with get_connection() as conn:
        states = dict_rows(
            conn.execute(
                """
                SELECT folder_rule_id
                FROM folder_rule_index_state
                WHERE status = ?
                ORDER BY folder_rule_id
                """,
                (INDEX_STATUS_READY,),
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
    params: list = [normalized]
    if not include_excluded:
        params.append(EXCLUDED_PROJECT)
    if activity_start_time:
        params.append(activity_start_time)

    if conn is None:
        with get_connection() as read_conn:
            rows = dict_rows(read_conn.execute(
                f"""
                SELECT idx.folder_rule_id, idx.file_name, idx.file_path, idx.normalized_path_key,
                       state.valid_from, fpr.folder_path, fpr.recursive, fpr.project_id, p.name AS project_name
                FROM folder_rule_file_index idx JOIN folder_rule_index_state state ON state.folder_rule_id = idx.folder_rule_id
                JOIN folder_project_rule fpr ON fpr.id = idx.folder_rule_id JOIN project p ON p.id = fpr.project_id
                WHERE idx.normalized_file_name = ? AND state.status = ? AND state.valid_from IS NOT NULL
                  AND fpr.enabled = 1 AND p.enabled = 1 AND COALESCE(p.is_archived, 0) = 0 AND COALESCE(p.is_deleted, 0) = 0
                  {project_clause} {time_clause} ORDER BY length(fpr.normalized_folder_key) DESC, idx.id ASC
                """, [*params[:1], INDEX_STATUS_READY, *params[1:]]).fetchall())
    else:
        rows = dict_rows(
            conn.execute(
                f"""
                SELECT
                    idx.folder_rule_id,
                    idx.file_name,
                    idx.file_path,
                    idx.normalized_path_key,
                    state.valid_from,
                    fpr.folder_path,
                    fpr.recursive,
                    fpr.project_id,
                    p.name AS project_name
                FROM folder_rule_file_index idx
                JOIN folder_rule_index_state state ON state.folder_rule_id = idx.folder_rule_id
                JOIN folder_project_rule fpr ON fpr.id = idx.folder_rule_id
                JOIN project p ON p.id = fpr.project_id
                WHERE idx.normalized_file_name = ?
                  AND state.status = ?
                  AND state.valid_from IS NOT NULL
                  AND fpr.enabled = 1
                  AND p.enabled = 1
                  AND COALESCE(p.is_archived, 0) = 0
                  AND COALESCE(p.is_deleted, 0) = 0
                  {project_clause}
                  {time_clause}
                ORDER BY length(fpr.normalized_folder_key) DESC, idx.id ASC
                """,
                [*params[:1], INDEX_STATUS_READY, *params[1:]],
            ).fetchall()
        )

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
        for rule_id in stale_rule_ids:
            mark_index_stale(rule_id, "indexed file path no longer exists")

    if conn is None and not results and not stale_rule_ids and request_refresh_on_miss:
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


def find_matching_folder_rule_for_file_name(file_name: str | None, activity_start_time: str | None = None, *, conn=None) -> dict | None:
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

    matched_rules: dict[int, dict] = {}
    for candidate in candidates:
        rule = folder_rule_service.find_matching_folder_rule(str(candidate.get("file_path") or ""), conn=conn)
        if rule:
            matched_rules[int(rule["project_id"])] = rule
    if len(matched_rules) != 1:
        return None
    return dict(next(iter(matched_rules.values())))


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

    matched_project_ids = set()
    for candidate in candidates:
        rule = folder_rule_service.find_matching_folder_rule(str(candidate.get("file_path") or ""))
        if rule:
            matched_project_ids.add(int(rule["project_id"]))
    if len(matched_project_ids) > 1:
        return False

    return any(int(candidate["folder_rule_id"]) == int(rule_id) for candidate in candidates)


def mark_index_stale(rule_id: int, reason: str = "") -> None:
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = ?, error_message = ?, refresh_requested = 1, updated_at = ?
            WHERE folder_rule_id = ?
            """,
            (INDEX_STATUS_STALE, reason, ts, int(rule_id)),
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
            ensure_index_states_for_folder_rules()
            while not stop_event.is_set():
                rule_ids = _pending_rule_ids()
                if not rule_ids:
                    break
                for rule_id in rule_ids:
                    if stop_event.is_set():
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
            WHERE status IN (?, ?)
               OR refresh_requested = 1
            ORDER BY
                CASE status
                    WHEN ? THEN 0
                    WHEN ? THEN 1
                    ELSE 2
                END,
                updated_at ASC,
                folder_rule_id ASC
            LIMIT ?
            """,
            (
                INDEX_STATUS_PENDING,
                INDEX_STATUS_STALE,
                INDEX_STATUS_STALE,
                INDEX_STATUS_PENDING,
                int(limit),
            ),
        ).fetchall()
    return [int(row["folder_rule_id"]) for row in rows]


def _load_folder_rule(rule_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM folder_project_rule WHERE id = ?", (int(rule_id),)).fetchone()
    return dict(row) if row else None


def _set_indexing(rule_id: int, ts: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = ?, error_message = NULL, refresh_requested = 0, updated_at = ?
            WHERE folder_rule_id = ?
            """,
            (INDEX_STATUS_INDEXING, ts, int(rule_id)),
        )


def _mark_ready(rule_id: int, valid_from: str, file_count: int) -> None:
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = ?,
                valid_from = ?,
                last_indexed_at = ?,
                last_checked_at = ?,
                file_count = ?,
                error_message = NULL,
                refresh_requested = 0,
                updated_at = ?
            WHERE folder_rule_id = ?
            """,
            (INDEX_STATUS_READY, valid_from, ts, ts, int(file_count), ts, int(rule_id)),
        )


def _mark_pending(rule_id: int) -> None:
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = ?, refresh_requested = 1, updated_at = ?
            WHERE folder_rule_id = ?
            """,
            (INDEX_STATUS_PENDING, ts, int(rule_id)),
        )


def _mark_error(rule_id: int, message: str) -> None:
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = ?,
                error_message = ?,
                refresh_requested = 0,
                file_count = 0,
                updated_at = ?
            WHERE folder_rule_id = ?
            """,
            (INDEX_STATUS_ERROR, message[:500], ts, int(rule_id)),
        )


def _clear_entries(rule_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM folder_rule_file_index WHERE folder_rule_id = ?", (int(rule_id),))


def _insert_entry_batch(batch: list[tuple]) -> None:
    if not batch:
        return
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO folder_rule_file_index(
                folder_rule_id, file_name, normalized_file_name, file_path,
                normalized_path_key, mtime, size, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(folder_rule_id, normalized_path_key) DO UPDATE SET
                file_name = excluded.file_name,
                normalized_file_name = excluded.normalized_file_name,
                file_path = excluded.file_path,
                mtime = excluded.mtime,
                size = excluded.size,
                updated_at = excluded.updated_at
            """,
            batch,
        )


def _entry_tuple(rule_id: int, item: dict, ts: str) -> tuple:
    file_path = str(item["path"])
    file_name = str(item["name"])
    return (
        int(rule_id),
        file_name,
        _normalize_index_file_name(file_name),
        file_path,
        normalize_path_key(file_path),
        item.get("mtime"),
        item.get("size"),
        ts,
        ts,
    )


def _iter_files(folder_path: str, recursive: bool, stop_event: threading.Event | None = None):
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


def _validate_rule_index(rule_id: int, stop_event: threading.Event | None = None) -> None:
    last_id = 0
    missing = False
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        with get_connection() as conn:
            rows = dict_rows(
                conn.execute(
                    """
                    SELECT id, file_path
                    FROM folder_rule_file_index
                    WHERE folder_rule_id = ?
                      AND id > ?
                    ORDER BY id
                    LIMIT ?
                    """,
                    (int(rule_id), last_id, _SCAN_BATCH_SIZE),
                ).fetchall()
            )
        if not rows:
            break
        for row in rows:
            last_id = int(row["id"])
            if not os.path.exists(str(row["file_path"] or "")):
                missing = True
                break
        if missing:
            mark_index_stale(rule_id, "indexed file path no longer exists")
            return
        if stop_event is not None:
            stop_event.wait(0.01)

    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            "UPDATE folder_rule_index_state SET last_checked_at = ?, updated_at = ? WHERE folder_rule_id = ?",
            (ts, ts, int(rule_id)),
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
    if not value:
        return ""
    return normalize_file_name(value)
