from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from ..constants import STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED, TIME_FORMAT, UNCATEGORIZED_PROJECT
from .context_service import recompute_context_assignments_for_date
from . import timeline_service
from .settings_service import get_setting


def get_summary(start_date: str, end_date: str, ensure_context: bool = True, include_live: bool = False) -> dict:
    if ensure_context:
        _ensure_context_range(start_date, end_date)
    rows = timeline_service.get_report_activity_rows(
        start_date,
        end_date,
        include_hidden=False,
        ensure_context=False,
    )
    total = sum(int(row.get("report_duration_seconds") or row.get("duration_seconds") or 0) for row in rows)
    effective = sum(
        int(row.get("report_duration_seconds") or row.get("duration_seconds") or 0)
        for row in rows
        if row.get("status") == STATUS_NORMAL
    )
    idle = sum(
        int(row.get("report_duration_seconds") or row.get("duration_seconds") or 0)
        for row in rows
        if row.get("status") == STATUS_IDLE
    )
    paused = sum(
        int(row.get("report_duration_seconds") or row.get("duration_seconds") or 0)
        for row in rows
        if row.get("status") == STATUS_PAUSED
    )
    excluded = sum(
        int(row.get("report_duration_seconds") or row.get("duration_seconds") or 0)
        for row in rows
        if row.get("status") == STATUS_EXCLUDED
    )
    live = _live_projection(start_date, end_date) if include_live else None
    if live is not None:
        live_duration = int(live["duration_seconds"])
        total += live_duration
        if live["status"] == STATUS_NORMAL:
            effective += live_duration
        elif live["status"] == STATUS_IDLE:
            idle += live_duration
        elif live["status"] == STATUS_PAUSED:
            paused += live_duration
        elif live["status"] == STATUS_EXCLUDED:
            excluded += live_duration
    project_stats = get_project_stats(start_date, end_date, ensure_context=False, include_live=False)
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
    if live is not None and live["status"] == STATUS_NORMAL:
        if live["project"] == UNCATEGORIZED_PROJECT:
            uncategorized += int(live["duration_seconds"])
        else:
            classified += int(live["duration_seconds"])
    return {
        "total_duration": total,
        "effective_duration": effective,
        "classified_duration": classified,
        "idle_duration": idle,
        "paused_duration": paused,
        "excluded_duration": excluded,
        "uncategorized_duration": uncategorized,
    }


def get_project_stats(start_date: str, end_date: str, ensure_context: bool = True, include_live: bool = False) -> list[dict]:
    if ensure_context:
        _ensure_context_range(start_date, end_date)
    groups: dict[str, dict] = {}
    for session in timeline_service.get_project_sessions_by_range(
        start_date,
        end_date,
        include_hidden=False,
        ensure_context=False,
    ):
        if session["status"] not in {STATUS_NORMAL, "mixed"}:
            continue
        project = str(session.get("project_name") or UNCATEGORIZED_PROJECT)
        group = groups.setdefault(project, {"project": project, "total_duration": 0, "record_count": 0})
        description = str(session.get("project_description") or "").strip()
        if description and not group.get("project_description"):
            group["project_description"] = description
        group["total_duration"] += int(session.get("duration_seconds") or 0)
        group["record_count"] += 1
    live = _live_projection(start_date, end_date) if include_live else None
    if live is not None and live["status"] == STATUS_NORMAL:
        project = str(live["project"] or UNCATEGORIZED_PROJECT)
        group = groups.setdefault(project, {"project": project, "total_duration": 0, "record_count": 0})
        if live.get("project_description") and not group.get("project_description"):
            group["project_description"] = live["project_description"]
        group["total_duration"] += int(live["duration_seconds"] or 0)
        group["record_count"] += 1
    return sorted(groups.values(), key=lambda row: (-int(row["total_duration"]), str(row["project"]).casefold()))


def get_uncategorized_duration(start_date: str, end_date: str) -> int:
    return sum(
        int(row["total_duration"])
        for row in get_project_stats(start_date, end_date)
        if row["project"] == UNCATEGORIZED_PROJECT
    )


def _ensure_context_range(start_date: str, end_date: str) -> None:
    current = date.fromisoformat(start_date) - timedelta(days=1)
    final = date.fromisoformat(end_date)
    while current <= final:
        recompute_context_assignments_for_date(current.isoformat())
        current += timedelta(days=1)


def _live_projection(start_date: str, end_date: str) -> dict | None:
    snapshot = _read_current_activity_snapshot()
    if not snapshot or bool(snapshot.get("is_persisted")) or _safe_int(snapshot.get("persisted_activity_id")):
        return None
    duration = _snapshot_elapsed_seconds(snapshot) + _safe_int(snapshot.get("extra_seconds"))
    if duration <= 0:
        return None
    report_date = timeline_service.get_default_report_date()
    if not (start_date <= report_date <= end_date):
        return None
    status = str(snapshot.get("status") or STATUS_NORMAL)
    project = str(snapshot.get("inferred_project_name") or UNCATEGORIZED_PROJECT).strip() or UNCATEGORIZED_PROJECT
    description = ""
    if project != UNCATEGORIZED_PROJECT:
        from . import project_service

        existing = project_service.get_project_by_name(project)
        description = str((existing or {}).get("description") or "")
    return {
        "status": status,
        "duration_seconds": duration,
        "project": project,
        "project_description": description,
    }


def _read_current_activity_snapshot() -> dict | None:
    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _snapshot_elapsed_seconds(snapshot: dict) -> int:
    fallback = _safe_int(snapshot.get("elapsed_seconds"))
    start_text = str(snapshot.get("start_time") or "")
    if start_text:
        try:
            start = datetime.strptime(start_text, TIME_FORMAT)
        except ValueError:
            return fallback
        seconds = int((datetime.now() - start).total_seconds())
        if 0 <= seconds <= 36 * 60 * 60:
            return seconds
    return fallback


def _safe_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
