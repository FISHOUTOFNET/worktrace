"""Read-only queries over durable clipboard facts."""

from __future__ import annotations

from ..constants import STATUS_NORMAL
from ..db import dict_rows, get_connection
from ..path_utils import normalize_path_key
from ..platforms.base import ActiveWindow


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
    return "\n".join(
        str(row["copied_text"] or "") for row in rows if row["copied_text"]
    )


def clipboard_times_for_activity_ids(
    conn,
    activity_ids: list[int],
) -> dict[int, list[str]]:
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
        result.setdefault(int(row["activity_id"]), []).append(
            str(row["copied_at"] or "")
        )
    return result


def find_activity_for_clipboard_event(
    source_window: ActiveWindow,
    copied_at: str,
) -> int | None:
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
                apa.project_id,
                p.name AS project_name
            FROM activity_clipboard_event ace
            JOIN activity_log a ON a.id = ace.activity_id
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN project p ON p.id = apa.project_id
            WHERE ace.copied_at BETWEEN ? AND ?
              AND a.is_deleted = 0
            ORDER BY ace.copied_at ASC, ace.id ASC
            """,
            (start_time, end_time),
        ).fetchall()
    return dict_rows(rows)


__all__ = [
    "clipboard_text_for_activity",
    "clipboard_times_for_activity_ids",
    "find_activity_for_clipboard_event",
    "list_file_text_mappings",
]
