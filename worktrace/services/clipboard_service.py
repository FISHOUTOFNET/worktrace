from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from ..constants import CLIPBOARD_RETENTION_DAYS, STATUS_NORMAL, TIME_FORMAT
from ..db import dict_rows, get_connection, now_str
from ..path_utils import normalize_path_key
from ..platforms.base import ActiveWindow
from .settings_service import get_bool_setting


def is_capture_enabled() -> bool:
    return get_bool_setting("clipboard_capture_enabled", False)


def record_clipboard_event(
    activity_id: int,
    text: str,
    source_window: ActiveWindow,
    copied_at: str | None = None,
    sequence_number: int | None = None,
) -> int | None:
    copied_text = str(text or "")
    if not copied_text:
        return None
    copied_time = copied_at or now_str()
    text_hash = _hash_text(copied_text)
    ts = now_str()
    with get_connection() as conn:
        activity = conn.execute(
            "SELECT id, status FROM activity_log WHERE id = ? AND is_deleted = 0",
            (activity_id,),
        ).fetchone()
        if not activity or activity["status"] != STATUS_NORMAL:
            return None
        existing = _find_duplicate_event(conn, int(activity_id), copied_time, text_hash, sequence_number)
        if existing is not None:
            return existing
        cur = conn.execute(
            """
            INSERT INTO activity_clipboard_event(
                activity_id, copied_at, app_name, process_name, window_title, file_path_hint,
                copied_text, text_hash, text_length, clipboard_sequence, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(activity_id),
                copied_time,
                source_window.app_name or "",
                source_window.process_name or "",
                source_window.window_title or "",
                source_window.file_path_hint,
                copied_text,
                text_hash,
                len(copied_text),
                sequence_number,
                ts,
                ts,
            ),
        )
        event_id = int(cur.lastrowid)
    _after_clipboard_change(int(activity_id), copied_time)
    prune_old_events()
    return event_id


def clipboard_text_for_activity(conn, activity_id: int) -> str:
    rows = conn.execute(
        """
        SELECT copied_text
        FROM activity_clipboard_event
        WHERE activity_id = ?
        ORDER BY copied_at ASC, id ASC
        """,
        (int(activity_id),),
    ).fetchall()
    return "\n".join(str(row["copied_text"] or "") for row in rows if row["copied_text"])


def clipboard_times_for_activity_ids(conn, activity_ids: list[int]) -> dict[int, list[str]]:
    ids = [int(value) for value in activity_ids]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT activity_id, copied_at
        FROM activity_clipboard_event
        WHERE activity_id IN ({placeholders})
        ORDER BY copied_at ASC, id ASC
        """,
        ids,
    ).fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(int(row["activity_id"]), []).append(str(row["copied_at"] or ""))
    return result


def find_activity_for_clipboard_event(source_window: ActiveWindow, copied_at: str) -> int | None:
    if not copied_at:
        return None
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, app_name, process_name, window_title, file_path_hint
            FROM activity_log
            WHERE is_deleted = 0
              AND status = ?
              AND start_time <= ?
              AND (end_time IS NULL OR end_time >= ?)
              AND app_name = ?
              AND process_name = ?
              AND window_title = ?
            ORDER BY id DESC
            """,
            (
                STATUS_NORMAL,
                copied_at,
                copied_at,
                source_window.app_name or "",
                source_window.process_name or "",
                source_window.window_title or "",
            ),
        ).fetchall()
    source_path = normalize_path_key(source_window.file_path_hint or "")
    for row in rows:
        row_path = normalize_path_key(row["file_path_hint"] or "")
        if source_path and row_path and source_path != row_path:
            continue
        return int(row["id"])
    return None


def list_file_text_mappings(start_time: str, end_time: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                ace.id,
                ace.activity_id,
                ace.copied_at,
                ace.copied_text,
                ace.text_hash,
                ace.text_length,
                COALESCE(a.file_path_hint, ace.file_path_hint, '') AS file_path,
                a.app_name,
                a.process_name,
                a.window_title,
                a.start_time,
                a.end_time,
                a.project_id,
                p.name AS project_name
            FROM activity_clipboard_event ace
            JOIN activity_log a ON a.id = ace.activity_id
            LEFT JOIN project p ON p.id = a.project_id
            WHERE ace.copied_at BETWEEN ? AND ?
              AND a.is_deleted = 0
            ORDER BY ace.copied_at ASC, ace.id ASC
            """,
            (start_time, end_time),
        ).fetchall()
    return dict_rows(rows)


def prune_old_events(retention_days: int = CLIPBOARD_RETENTION_DAYS, now: str | None = None) -> int:
    cutoff = _retention_cutoff(retention_days, now)
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM activity_clipboard_event WHERE copied_at < ?",
            (cutoff,),
        )
        return int(cur.rowcount or 0)


def _find_duplicate_event(
    conn,
    activity_id: int,
    copied_at: str,
    text_hash: str,
    sequence_number: int | None,
) -> int | None:
    if sequence_number is not None:
        row = conn.execute(
            """
            SELECT id
            FROM activity_clipboard_event
            WHERE clipboard_sequence = ?
              AND activity_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (sequence_number, activity_id),
        ).fetchone()
        if row:
            return int(row["id"])
    row = conn.execute(
        """
        SELECT id
        FROM activity_clipboard_event
        WHERE activity_id = ?
          AND copied_at = ?
          AND text_hash = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (activity_id, copied_at, text_hash),
    ).fetchone()
    return int(row["id"]) if row else None


def _after_clipboard_change(activity_id: int, copied_at: str) -> None:
    try:
        from .project_inference_service import assign_project_for_activity

        assign_project_for_activity(activity_id)
    except Exception:
        pass
    try:
        from .context_service import invalidate_context_recompute_cache

        invalidate_context_recompute_cache(str(copied_at or "")[:10] or None)
    except Exception:
        pass


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _retention_cutoff(retention_days: int, now: str | None) -> str:
    if now:
        base = datetime.strptime(now, TIME_FORMAT)
    else:
        base = datetime.now()
    return (base - timedelta(days=max(0, int(retention_days)))).strftime(TIME_FORMAT)
