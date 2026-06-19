from __future__ import annotations

from datetime import date, timedelta

from ..constants import STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED, UNCATEGORIZED_PROJECT
from ..db import get_connection
from .context_service import recompute_context_assignments_for_date
from . import timeline_service


def _range_bounds(start_date: str, end_date: str) -> tuple[str, str]:
    return f"{start_date} 00:00:00", f"{end_date} 23:59:59"


def get_summary(start_date: str, end_date: str) -> dict:
    _ensure_context_range(start_date, end_date)
    start, end = _range_bounds(start_date, end_date)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(COALESCE(duration_seconds, 0)), 0) AS total_duration,
                COALESCE(SUM(CASE WHEN status = ? THEN COALESCE(duration_seconds, 0) ELSE 0 END), 0)
                    AS effective_duration,
                COALESCE(SUM(CASE WHEN status = ? THEN COALESCE(duration_seconds, 0) ELSE 0 END), 0)
                    AS idle_duration,
                COALESCE(SUM(CASE WHEN status = ? THEN COALESCE(duration_seconds, 0) ELSE 0 END), 0)
                    AS paused_duration,
                COALESCE(SUM(CASE WHEN status = ? THEN COALESCE(duration_seconds, 0) ELSE 0 END), 0)
                    AS excluded_duration
            FROM activity_log
            WHERE is_deleted = 0
              AND is_hidden = 0
              AND start_time BETWEEN ? AND ?
            """,
            (STATUS_NORMAL, STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, start, end),
        ).fetchone()
    total = int(row["total_duration"] or 0)
    effective = int(row["effective_duration"] or 0)
    idle = int(row["idle_duration"] or 0)
    paused = int(row["paused_duration"] or 0)
    excluded = int(row["excluded_duration"] or 0)
    project_stats = get_project_stats(start_date, end_date, ensure_context=False)
    uncategorized = sum(
        int(row["total_duration"])
        for row in project_stats
        if row["project"] == UNCATEGORIZED_PROJECT
    )
    classified = sum(
        int(row["total_duration"])
        for row in project_stats
        if row["project"] != UNCATEGORIZED_PROJECT
    )
    return {
        "total_duration": total,
        "effective_duration": effective,
        "classified_duration": classified,
        "idle_duration": idle,
        "paused_duration": paused,
        "excluded_duration": excluded,
        "uncategorized_duration": uncategorized,
    }


def get_project_stats(start_date: str, end_date: str, ensure_context: bool = True) -> list[dict]:
    if ensure_context:
        _ensure_context_range(start_date, end_date)
    groups: dict[str, dict] = {}
    current = date.fromisoformat(start_date)
    final = date.fromisoformat(end_date)
    while current <= final:
        for session in timeline_service.get_project_sessions_by_date(
            current.isoformat(),
            include_hidden=False,
            ensure_context=False,
        ):
            if session["status"] not in {STATUS_NORMAL, "mixed"}:
                continue
            project = str(session.get("project_name") or UNCATEGORIZED_PROJECT)
            group = groups.setdefault(project, {"project": project, "total_duration": 0, "record_count": 0})
            group["total_duration"] += int(session.get("duration_seconds") or 0)
            group["record_count"] += int(session.get("event_count") or 0)
        current += timedelta(days=1)
    return sorted(groups.values(), key=lambda row: (-int(row["total_duration"]), str(row["project"]).casefold()))


def get_uncategorized_duration(start_date: str, end_date: str) -> int:
    return sum(
        int(row["total_duration"])
        for row in get_project_stats(start_date, end_date)
        if row["project"] == UNCATEGORIZED_PROJECT
    )


def _ensure_context_range(start_date: str, end_date: str) -> None:
    current = date.fromisoformat(start_date)
    final = date.fromisoformat(end_date)
    while current <= final:
        recompute_context_assignments_for_date(current.isoformat())
        current += timedelta(days=1)
