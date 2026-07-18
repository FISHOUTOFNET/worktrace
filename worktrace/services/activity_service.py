"""Activity queries and post-capture commands.

Durable open-row lifecycle transitions are owned exclusively by
``activity_lifecycle_service`` and ``activity_fact_repository``. Path/resource
mutations are delegated to ``activity_resource_command_service``.
"""

from __future__ import annotations

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


def _attach_attribution_fields(row: dict, uncategorized_id: int) -> dict:
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
