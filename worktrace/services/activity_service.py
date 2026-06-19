from __future__ import annotations

from datetime import datetime
from typing import Any

from ..constants import (
    SOURCE_AUTO,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_NORMAL,
    TIME_FORMAT,
)
from ..db import dict_rows, get_connection, now_str
from ..resource_patterns import extract_anchor_file_name
from .project_service import get_or_create_uncategorized_project


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def _duration_seconds(start_time: str, end_time: str) -> tuple[int, bool]:
    seconds = int((_parse_time(end_time) - _parse_time(start_time)).total_seconds())
    if seconds < 0:
        return 0, True
    return seconds, False


def create_activity(
    app_name: str,
    process_name: str,
    window_title: str,
    status: str = STATUS_NORMAL,
    source: str = SOURCE_AUTO,
    start_time: str | None = None,
    is_billable: bool | None = None,
    project_id: int | None = None,
    resource_id: int | None = None,
    file_path_hint: str | None = None,
    note: str | None = None,
    is_confirmed: bool = False,
    auto_classified: bool = False,
    manual_override: bool = False,
) -> int:
    ts = now_str()
    start = start_time or ts
    project = project_id if project_id is not None else get_or_create_uncategorized_project()
    manual_assignment = bool(manual_override or project_id is not None)
    billable = int(is_billable if is_billable is not None else status == STATUS_NORMAL)
    if status == STATUS_EXCLUDED:
        billable = 0
    with get_connection() as conn:
        open_rows = conn.execute("SELECT id FROM activity_log WHERE end_time IS NULL").fetchall()
        for row in open_rows:
            _close_activity_in_conn(conn, int(row["id"]), start)
        cur = conn.execute(
            """
            INSERT INTO activity_log(
                start_time, end_time, duration_seconds, app_name, process_name, window_title,
                file_path_hint, status, source, is_billable, is_deleted, is_hidden, is_confirmed,
                auto_classified, manual_override, project_id, resource_id, note, created_at, updated_at
            )
            VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                start,
                app_name,
                process_name,
                window_title,
                file_path_hint,
                status,
                source,
                billable,
                int(is_confirmed),
                int(auto_classified),
                int(manual_assignment),
                project,
                resource_id,
                note,
                ts,
                ts,
            ),
        )
        activity_id = int(cur.lastrowid)
        assignment_source = "manual" if manual_assignment else "uncategorized"
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id) DO NOTHING
            """,
            (
                activity_id,
                project,
                100 if manual_assignment else 0,
                assignment_source,
                int(manual_assignment),
                ts,
                ts,
            ),
        )
        return activity_id


def _close_activity_in_conn(conn, activity_id: int, end_time: str) -> None:
    row = conn.execute("SELECT start_time, status FROM activity_log WHERE id = ?", (activity_id,)).fetchone()
    if not row:
        return
    duration, is_error = _duration_seconds(row["start_time"], end_time)
    status = STATUS_ERROR if is_error else row["status"]
    conn.execute(
        """
        UPDATE activity_log
        SET end_time = ?, duration_seconds = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (end_time, duration, status, now_str(), activity_id),
    )


def close_activity(activity_id: int, end_time: str) -> None:
    with get_connection() as conn:
        _close_activity_in_conn(conn, activity_id, end_time)


def close_current_open_record(end_time: str | None = None) -> None:
    end = end_time or now_str()
    with get_connection() as conn:
        rows = conn.execute("SELECT id FROM activity_log WHERE end_time IS NULL ORDER BY id").fetchall()
        for row in rows:
            _close_activity_in_conn(conn, int(row["id"]), end)


def increment_activity_duration(activity_id: int, seconds: int) -> None:
    seconds = max(0, int(seconds or 0))
    if seconds <= 0:
        return
    with get_connection() as conn:
        row = conn.execute(
            "SELECT duration_seconds FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not row:
            return
        duration = int(row["duration_seconds"] or 0) + seconds
        conn.execute(
            """
            UPDATE activity_log
            SET duration_seconds = ?, updated_at = ?
            WHERE id = ?
            """,
            (duration, now_str(), activity_id),
        )


def set_activity_duration(activity_id: int, seconds: int) -> None:
    seconds = max(0, int(seconds or 0))
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET duration_seconds = ?, updated_at = ?
            WHERE id = ?
            """,
            (seconds, now_str(), activity_id),
        )


def get_latest_closed_auto_normal_activity() -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM activity_log
            WHERE is_deleted = 0
              AND is_hidden = 0
              AND status = ?
              AND source = ?
              AND end_time IS NOT NULL
            ORDER BY end_time DESC, id DESC
            LIMIT 1
            """,
            (STATUS_NORMAL, SOURCE_AUTO),
        ).fetchone()
    return dict(row) if row else None


def get_open_activity() -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_log WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _activity_select_sql(where: str) -> str:
    return f"""
        SELECT
            a.*,
            p.name AS project_name,
            r.display_name AS resource_display_name,
            r.resource_role,
            r.resource_type,
            r.full_path AS resource_full_path,
            r.parent_dir AS resource_parent_dir,
            r.file_stem AS resource_file_stem
        FROM activity_log a
        LEFT JOIN project p ON p.id = a.project_id
        LEFT JOIN resource r ON r.id = a.resource_id
        WHERE {where}
        ORDER BY a.start_time DESC, a.id DESC
    """


def get_activities_by_date(date: str) -> list[dict]:
    return get_activities_by_range(date, date)


def get_activities_by_range(start_date: str, end_date: str) -> list[dict]:
    start = f"{start_date} 00:00:00"
    end = f"{end_date} 23:59:59"
    with get_connection() as conn:
        rows = conn.execute(
            _activity_select_sql("a.is_deleted = 0 AND a.start_time BETWEEN ? AND ?"),
            (start, end),
        ).fetchall()
    return dict_rows(rows)


def get_activity(activity_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(_activity_select_sql("a.id = ?"), (activity_id,)).fetchone()
    return dict(row) if row else None


def activity_display_name(activity: dict) -> str:
    resource_name = str(activity.get("resource_display_name") or "").strip()
    if activity.get("resource_role") == "anchor" and resource_name:
        return resource_name
    title_file = extract_anchor_file_name(activity.get("window_title"))
    if title_file:
        return title_file
    return str(activity.get("app_name") or activity.get("process_name") or "").strip()


def update_activity_project(activity_id: int, project_id: int, manual: bool = True) -> None:
    update_activities_project([activity_id], project_id, manual=manual)


def update_activity_resource(activity_id: int, resource_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET resource_id = ?, updated_at = ? WHERE id = ?",
            (resource_id, now_str(), activity_id),
        )


def update_activity_file_path_hint(activity_id: int, file_path_hint: str) -> None:
    if not (file_path_hint or "").strip():
        return
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET file_path_hint = ?, updated_at = ? WHERE id = ?",
            (file_path_hint, now_str(), activity_id),
        )
    from . import resource_service
    from .project_inference_service import assign_project_for_activity

    resource_service.refresh_activity_resource(activity_id)
    assign_project_for_activity(activity_id)


def update_activities_project(activity_ids: list[int], project_id: int, manual: bool = True) -> None:
    if not activity_ids:
        return
    ts = now_str()
    placeholders = ",".join("?" for _ in activity_ids)
    source = "manual" if manual else "anchor_context"
    confidence = 100 if manual else 60
    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE activity_log
            SET project_id = ?,
                manual_override = CASE WHEN ? = 1 THEN 1 ELSE manual_override END,
                is_confirmed = CASE WHEN ? = 1 THEN 1 ELSE is_confirmed END,
                updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [project_id, int(manual), int(manual), ts, *activity_ids],
        )
        for activity_id in activity_ids:
            conn.execute(
                """
                INSERT INTO activity_project_assignment(
                    activity_id, project_id, confidence, source, is_manual, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    is_manual = excluded.is_manual,
                    updated_at = excluded.updated_at
                """,
                (activity_id, project_id, confidence, source, int(manual), ts, ts),
            )


def finalize_created_activity(activity_id: int) -> None:
    from .project_inference_service import process_new_activity

    process_new_activity(activity_id)


def update_activity_note(activity_id: int, note: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET note = ?, source = 'manual', is_confirmed = 1, updated_at = ? WHERE id = ?",
            (note, now_str(), activity_id),
        )


def set_activity_billable(activity_id: int, is_billable: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_billable = ?, is_confirmed = 1, updated_at = ? WHERE id = ?",
            (int(is_billable), now_str(), activity_id),
        )


def set_activity_confirmed(activity_id: int, is_confirmed: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_confirmed = ?, updated_at = ? WHERE id = ?",
            (int(is_confirmed), now_str(), activity_id),
        )


def soft_delete_activity(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_deleted = 1, updated_at = ? WHERE id = ?",
            (now_str(), activity_id),
        )


def update_activity_fields(activity_id: int, **fields: Any) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "source",
        "is_billable",
        "is_hidden",
        "is_confirmed",
        "auto_classified",
        "manual_override",
        "project_id",
        "resource_id",
        "note",
    }
    items = [(key, value) for key, value in fields.items() if key in allowed]
    if not items:
        return
    sql = ", ".join(f"{key} = ?" for key, _ in items)
    values = [value for _, value in items]
    values.extend([now_str(), activity_id])
    with get_connection() as conn:
        conn.execute(f"UPDATE activity_log SET {sql}, updated_at = ? WHERE id = ?", values)
