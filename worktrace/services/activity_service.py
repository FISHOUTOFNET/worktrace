"""Activity queries and post-capture commands.

Durable open-row lifecycle transitions are owned exclusively by
``activity_lifecycle_service`` and ``activity_fact_repository``. Path/resource
mutations are delegated to ``activity_resource_command_service``.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ..constants import (
    SOURCE_AUTO,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    UNCATEGORIZED_PROJECT,
)
from ..db import dict_rows, get_connection
from ..platforms.base import ActiveWindow
from ..resources.resource_builders import make_system_resource
from ..resources.types import DetectedResource
from .project_attribution_policy import official_project_fields
from .resource_service import attach_resource
from .system_project_service import require_uncategorized_project_id


def _detect_resource_for_activity(
    app_name: str,
    process_name: str,
    window_title: str,
    file_path_hint: str | None,
    status: str,
    start_time: str | None = None,
) -> DetectedResource:
    """Resolve a resource for a newly observed activity before its write UoW."""

    from ..resources.detectors import detect_resource

    if status in (STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR):
        return make_system_resource(status, app_name, process_name, window_title)
    return detect_resource(
        ActiveWindow(
            app_name=app_name,
            process_name=process_name,
            window_title=window_title,
            file_path_hint=file_path_hint,
            activity_start_time=start_time,
        )
    )


def get_latest_closed_auto_normal_activity(after_time: str | None = None) -> dict | None:
    time_clause = ""
    params: list[Any] = [STATUS_NORMAL, SOURCE_AUTO]
    if after_time:
        time_clause = "AND end_time > ?"
        params.append(after_time)
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT *
            FROM activity_log
            WHERE is_deleted = 0
              AND is_hidden = 0
              AND status = ?
              AND source = ?
              AND end_time IS NOT NULL
              {time_clause}
            ORDER BY end_time DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    return dict(row) if row else None


def _activity_select_sql(where: str) -> str:
    return f"""
        SELECT
            a.*,
            pe.name AS project_name,
            apa.source AS assignment_source,
            apa.is_manual AS assignment_is_manual,
            apa.suggested_project_name,
            apa.project_id AS effective_project_id,
            pe.name AS effective_project_name,
            pe.description AS effective_project_description
        FROM activity_log a
        LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
        LEFT JOIN project pe ON pe.id = apa.project_id
        WHERE {where}
        ORDER BY a.start_time DESC, a.id DESC
    """


def get_open_activity() -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            _activity_select_sql("a.end_time IS NULL").replace(
                "ORDER BY a.start_time DESC, a.id DESC",
                "ORDER BY a.id DESC LIMIT 1",
            )
        ).fetchone()
        if row is None:
            return None
        uncategorized_id = require_uncategorized_project_id(conn)
        return _attach_attribution_fields(dict(row), uncategorized_id)


def get_activities_by_date(date: str) -> list[dict]:
    return get_activities_by_range(date, date)


def get_activity_structure_marker_by_date(date: str) -> dict:
    """Return the legacy structural marker without attaching resource facts."""

    start = f"{date} 00:00:00"
    end = f"{date} 23:59:59"
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS row_count,
                SUM(CASE WHEN is_deleted = 0 THEN 1 ELSE 0 END) AS visible_row_count,
                COALESCE(MAX(id), 0) AS max_id,
                COALESCE(MAX(CASE WHEN end_time IS NOT NULL THEN updated_at ELSE '' END), '') AS closed_max_updated_at,
                COALESCE(MAX(updated_at), '') AS max_updated_at,
                SUM(CASE WHEN end_time IS NULL AND is_deleted = 0 THEN 1 ELSE 0 END) AS open_row_count,
                COALESCE(MAX(CASE WHEN end_time IS NULL AND is_deleted = 0 THEN id ELSE 0 END), 0) AS open_max_id,
                COALESCE(MAX(CASE WHEN end_time IS NULL AND is_deleted = 0 THEN updated_at ELSE '' END), '') AS open_max_updated_at,
                COALESCE(MAX(CASE WHEN end_time IS NULL AND is_deleted = 0 THEN COALESCE(end_time, '') ELSE '' END), '') AS open_end_time_presence,
                SUM(CASE WHEN is_hidden != 0 THEN 1 ELSE 0 END) AS hidden_count,
                SUM(CASE WHEN is_deleted != 0 THEN 1 ELSE 0 END) AS deleted_count
            FROM activity_log
            WHERE start_time BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchone()
        signature_row = conn.execute(
            """
            SELECT COALESCE(GROUP_CONCAT(sig, '#'), '') AS structural_signature
            FROM (
                SELECT
                    id || '|' || COALESCE(start_time, '') || '|' ||
                    CASE WHEN end_time IS NULL THEN '1' ELSE '0' END || '|' ||
                    COALESCE(end_time, '') || '|' || COALESCE(status, '') || '|' ||
                    COALESCE(assignment_project_id, 0) || '|' ||
                    COALESCE(assignment_source, '') || '|' ||
                    COALESCE(assignment_is_manual, 0) || '|' ||
                    COALESCE(assignment_updated_at, '') || '|' ||
                    COALESCE(source, '') || '|' || COALESCE(is_deleted, 0) || '|' ||
                    COALESCE(is_hidden, 0) AS sig
                FROM (
                    SELECT
                        a.id, a.start_time, a.end_time, a.status, a.source,
                        a.is_deleted, a.is_hidden,
                        apa.project_id AS assignment_project_id,
                        apa.source AS assignment_source,
                        apa.is_manual AS assignment_is_manual,
                        apa.updated_at AS assignment_updated_at
                    FROM activity_log a
                    LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
                    WHERE a.start_time BETWEEN ? AND ?
                    ORDER BY a.id
                )
            )
            """,
            (start, end),
        ).fetchone()
    if row is None:
        return {
            "row_count": 0,
            "visible_row_count": 0,
            "max_id": 0,
            "closed_max_updated_at": "",
            "max_updated_at": "",
            "open_row_count": 0,
            "open_max_id": 0,
            "open_max_updated_at": "",
            "open_end_time_presence": "",
            "hidden_count": 0,
            "deleted_count": 0,
            "structural_signature": "",
        }
    return {
        "row_count": int(row["row_count"] or 0),
        "visible_row_count": int(row["visible_row_count"] or 0),
        "max_id": int(row["max_id"] or 0),
        "closed_max_updated_at": str(row["closed_max_updated_at"] or ""),
        "max_updated_at": str(row["max_updated_at"] or ""),
        "open_row_count": int(row["open_row_count"] or 0),
        "open_max_id": int(row["open_max_id"] or 0),
        "open_max_updated_at": str(row["open_max_updated_at"] or ""),
        "open_end_time_presence": str(row["open_end_time_presence"] or ""),
        "hidden_count": int(row["hidden_count"] or 0),
        "deleted_count": int(row["deleted_count"] or 0),
        "structural_signature": hashlib.sha1(
            str(
                signature_row["structural_signature"] if signature_row else ""
            ).encode("utf-8")
        ).hexdigest(),
    }


def _attach_attribution_fields(row: dict, uncategorized_id: int) -> dict:
    row["raw_project_id_deprecated"] = row.get("project_id")
    if row.get("effective_project_id") is not None:
        row["project_id"] = int(row.get("effective_project_id") or 0)
        row["project_name"] = row.get("effective_project_name") or UNCATEGORIZED_PROJECT
        row["project_description"] = row.get("effective_project_description") or ""
    else:
        row["project_id"] = uncategorized_id
        row["project_name"] = UNCATEGORIZED_PROJECT
        row["project_description"] = ""
    row.update(official_project_fields(row, uncategorized_id))
    return row


def get_activities_by_range(start_date: str, end_date: str) -> list[dict]:
    start = f"{start_date} 00:00:00"
    end = f"{end_date} 23:59:59"
    with get_connection() as conn:
        uncategorized_id = require_uncategorized_project_id(conn)
        rows = dict_rows(
            conn.execute(
                _activity_select_sql(
                    "a.is_deleted = 0 AND a.start_time BETWEEN ? AND ?"
                ),
                (start, end),
            ).fetchall()
        )
        return [
            _attach_attribution_fields(
                attach_resource(row, conn=conn),
                uncategorized_id,
            )
            for row in rows
        ]


def get_activity(activity_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            _activity_select_sql("a.id = ?"),
            (int(activity_id),),
        ).fetchone()
        if row is None:
            return None
        uncategorized_id = require_uncategorized_project_id(conn)
        return _attach_attribution_fields(
            attach_resource(dict(row), conn=conn),
            uncategorized_id,
        )


def activity_display_name(activity: dict) -> str:
    name = activity.get("resource_display_name") or activity.get("activity_display_name")
    if name:
        return str(name).strip()
    return attach_resource(activity)["activity_display_name"]


def update_activity_file_path_hint(activity_id: int, file_path_hint: str) -> None:
    from .activity_resource_command_service import update_activity_file_path_hint as command

    command(int(activity_id), file_path_hint)


def _sync_activity_resource_after_path_update(
    conn,
    activity_id: int,
    file_path_hint: str,
) -> None:
    """Transitional private wrapper; the command owner controls its own UoW."""

    from .activity_resource_command_service import update_activity_file_path_hint as command

    command(int(activity_id), file_path_hint)


def update_project_editable_activities_project(
    activity_ids: list[int],
    project_id: int,
) -> None:
    raise ValueError("activity_level_project_edit_removed")


def update_project_editable_activity_note(activity_id: int, note: str) -> None:
    raise ValueError("activity_level_note_edit_removed")
