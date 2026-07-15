"""Public read-only fact queries used by canonical report projection."""

from __future__ import annotations

from ..constants import UNCATEGORIZED_PROJECT
from ..db import get_connection
from . import session_boundary_service, timeline_service


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
    return timeline_service.get_report_activity_rows(
        start_date,
        end_date,
        conn=conn,
    )


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


__all__ = [
    "boundary_times_for_rows",
    "get_uncategorized_project_id",
    "load_report_activity_rows",
    "session_sort_key",
]
