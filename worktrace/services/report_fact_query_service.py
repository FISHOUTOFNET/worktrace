"""Independent read-only fact repository for canonical report projection."""

from __future__ import annotations

from datetime import date as date_type, datetime, time as datetime_time, timedelta

from ..constants import DEFAULT_CONTEXT_CARRY_MINUTES, TIME_FORMAT, UNCATEGORIZED_PROJECT
from ..db import get_connection
from . import clipboard_service, session_boundary_service
from .context_service import ReportContextProjection
from .project_attribution_policy import official_project_fields, report_project_fields
from .settings_service import get_int_setting


def get_uncategorized_project_id(conn=None) -> int:
    """Return the canonical uncategorized project id."""

    if conn is not None:
        row = conn.execute(
            "SELECT id FROM project WHERE name = ?",
            (UNCATEGORIZED_PROJECT,),
        ).fetchone()
        if not row:
            raise ValueError("report_context_not_ready")
        return int(row["id"])
    with get_connection() as read_conn:
        return get_uncategorized_project_id(read_conn)


def load_report_activity_rows(
    start_date: str,
    end_date: str,
    *,
    conn=None,
) -> list[dict]:
    """Load canonical persisted facts without routing through a page adapter."""

    if conn is None:
        with get_connection() as read_conn:
            return load_report_activity_rows(
                start_date,
                end_date,
                conn=read_conn,
            )

    uncategorized_id = get_uncategorized_project_id(conn)
    rows = _load_fact_rows(conn, start_date, end_date)
    boundaries = boundary_times_for_rows(rows, conn=conn)
    activity_ids = [int(row["id"]) for row in rows if int(row.get("id") or 0)]
    clipboard_times = clipboard_service.clipboard_times_for_activity_ids(
        conn,
        activity_ids,
    )
    carry_minutes = max(
        0,
        get_int_setting(
            "context_carry_minutes",
            DEFAULT_CONTEXT_CARRY_MINUTES,
            conn=conn,
        ),
    )
    attributed = ReportContextProjection.build(
        rows,
        carry_minutes=carry_minutes,
        boundary_times=boundaries,
        clipboard_times=clipboard_times,
    ).rows
    result: list[dict] = []
    for row in attributed:
        result.extend(_split_calendar_rows(dict(row)))
    return [
        row
        for row in result
        if start_date <= str(row.get("report_date") or "") <= end_date
    ]


def boundary_times_for_rows(rows: list[dict], *, conn=None) -> list[str]:
    ranges = [
        str(value)
        for row in rows
        for value in (row.get("start_time"), row.get("end_time"))
        if value
    ]
    if not ranges:
        return []
    boundaries = session_boundary_service.list_boundaries(
        min(ranges),
        max(ranges),
        conn=conn,
    )
    return [
        str(row["occurred_at"])
        for row in boundaries
        if row.get("occurred_at")
    ]


def session_sort_key(session: dict) -> tuple[str, int]:
    activity_ids = [int(value) for value in session.get("activity_ids") or []]
    start_id = min(activity_ids) if activity_ids else 0
    return (
        str(session.get("sort_time") or session.get("start_time") or ""),
        start_id,
    )


def _load_fact_rows(conn, start_date: str, end_date: str) -> list[dict]:
    load_start_day = date_type.fromisoformat(start_date) - timedelta(days=1)
    load_end_day = date_type.fromisoformat(end_date) + timedelta(days=2)
    load_start = f"{load_start_day.isoformat()} 00:00:00"
    load_end = f"{load_end_day.isoformat()} 00:00:00"
    raw_rows = conn.execute(
        """
        SELECT
            a.*,
            apa.suggested_project_name,
            apa.source AS assignment_source,
            apa.is_manual AS assignment_is_manual,
            apa.project_id AS effective_project_id,
            p.name AS effective_project_name,
            p.description AS effective_project_description,
            COALESCE(p.is_archived, 0) AS effective_project_is_archived,
            COALESCE(p.is_deleted, 0) AS effective_project_is_deleted,
            ar.resource_kind AS joined_resource_kind,
            ar.resource_subtype AS joined_resource_subtype,
            ar.display_name AS joined_resource_display_name,
            ar.identity_key AS joined_resource_identity_key,
            ar.is_anchor AS joined_resource_is_anchor,
            ar.path_hint AS joined_resource_path_hint,
            ar.uri_host AS joined_resource_uri_host
        FROM activity_log a
        LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
        LEFT JOIN project p ON p.id = apa.project_id
        LEFT JOIN activity_resource ar ON ar.activity_id = a.id
        WHERE a.is_deleted = 0
          AND a.is_hidden = 0
          AND (a.start_time >= ? OR a.end_time IS NULL OR a.end_time >= ?)
          AND (a.end_time IS NULL OR a.start_time <= ?)
        ORDER BY a.start_time ASC, a.id ASC
        """,
        (load_start, load_start, load_end),
    ).fetchall()
    uncategorized_id = get_uncategorized_project_id(conn)
    rows: list[dict] = []
    for raw in raw_rows:
        row = dict(raw)
        _attach_resource_fields(row)
        row.update(official_project_fields(row, uncategorized_id))
        row.update(report_project_fields(row, uncategorized_id))
        row["is_suggested_project"] = False
        rows.append(row)
    return rows


def _attach_resource_fields(row: dict) -> None:
    kind = row.pop("joined_resource_kind", None)
    subtype = row.pop("joined_resource_subtype", None)
    display_name = row.pop("joined_resource_display_name", None)
    identity_key = row.pop("joined_resource_identity_key", None)
    is_anchor = row.pop("joined_resource_is_anchor", None)
    path_hint = row.pop("joined_resource_path_hint", None)
    uri_host = row.pop("joined_resource_uri_host", None)
    if kind is None or not identity_key:
        raise ValueError("data_repair_required")
    row.update(
        {
            "resource_kind": kind,
            "resource_subtype": subtype,
            "resource_display_name": display_name,
            "resource_identity_key": identity_key,
            "resource_is_anchor": bool(is_anchor),
            "resource_path_hint": path_hint,
            "resource_uri_host": uri_host,
            "activity_display_name": display_name or row.get("app_name") or "",
            "activity_identity_key": identity_key,
        }
    )


def _split_calendar_rows(row: dict) -> list[dict]:
    start = _parse_time(row.get("start_time"))
    if start is None:
        return []
    duration = max(0, int(row.get("duration_seconds") or 0))
    raw_end = _parse_time(row.get("end_time"))
    is_in_progress = raw_end is None
    if duration <= 0:
        item = dict(row)
        item["report_date"] = start.date().isoformat()
        item["report_duration_seconds"] = 0
        item["report_slice"] = False
        item["is_in_progress"] = is_in_progress
        return [item]
    end = raw_end
    if end is None or end < start:
        end = start + timedelta(seconds=duration)
    result: list[dict] = []
    current = start
    while current < end:
        next_midnight = datetime.combine(
            current.date() + timedelta(days=1),
            datetime_time.min,
        )
        current_end = min(end, next_midnight)
        seconds = max(0, int((current_end - current).total_seconds()))
        if seconds <= 0:
            break
        item = dict(row)
        item["start_time"] = current.strftime(TIME_FORMAT)
        item["end_time"] = current_end.strftime(TIME_FORMAT)
        item["duration_seconds"] = seconds
        item["report_date"] = current.date().isoformat()
        item["report_duration_seconds"] = seconds
        item["report_slice"] = True
        item["is_in_progress"] = is_in_progress
        result.append(item)
        current = current_end
    return result


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        return None


__all__ = [
    "boundary_times_for_rows",
    "get_uncategorized_project_id",
    "load_report_activity_rows",
    "session_sort_key",
]
