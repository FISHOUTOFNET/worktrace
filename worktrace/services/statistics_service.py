from __future__ import annotations

from datetime import date, timedelta

from ..constants import STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED, UNCATEGORIZED_PROJECT
from ..db import get_connection
from .context_service import recompute_context_assignments_for_date
from . import timeline_service


def _range_bounds(start_date: str, end_date: str) -> tuple[str, str]:
    return f"{start_date} 00:00:00", f"{end_date} 23:59:59"


def _sum_duration(where: str, params: tuple = ()) -> int:
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT COALESCE(SUM(duration_seconds), 0) AS total FROM activity_log WHERE {where}",
            params,
        ).fetchone()
    return int(row["total"] or 0)


def get_summary(start_date: str, end_date: str) -> dict:
    _ensure_context_range(start_date, end_date)
    start, end = _range_bounds(start_date, end_date)
    base = "is_deleted = 0 AND is_hidden = 0 AND start_time BETWEEN ? AND ?"
    params = (start, end)
    total = _sum_duration(base, params)
    effective = _sum_duration(base + " AND status = ?", params + (STATUS_NORMAL,))
    idle = _sum_duration(base + " AND status = ?", params + (STATUS_IDLE,))
    paused = _sum_duration(base + " AND status = ?", params + (STATUS_PAUSED,))
    excluded = _sum_duration(base + " AND status = ?", params + (STATUS_EXCLUDED,))
    project_stats = get_project_stats(start_date, end_date)
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


def get_project_stats(start_date: str, end_date: str) -> list[dict]:
    groups: dict[str, dict] = {}
    current = date.fromisoformat(start_date)
    final = date.fromisoformat(end_date)
    while current <= final:
        for session in timeline_service.get_project_sessions_by_date(current.isoformat(), include_hidden=False):
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
