from __future__ import annotations

import json
from datetime import date, timedelta

from ..constants import STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED, UNCATEGORIZED_PROJECT
from .context_service import recompute_context_assignments_for_date
from . import timeline_service
from .live_time_service import safe_int, snapshot_elapsed_seconds, snapshot_extra_seconds
from .settings_service import get_setting

# Phase 4A: maximum inclusive calendar-day span accepted by the read-only
# statistics/export summary. A 31-day span (e.g. 2026-06-01..2026-07-01) is
# allowed; anything wider is rejected as ``range_too_large`` so the first
# version does not read an unbounded amount of data.
STATISTICS_SUMMARY_MAX_RANGE_DAYS = 31

# Phase 4A: display-safe Chinese labels for the by_status breakdown. The raw
# status codes (``normal`` / ``idle`` / ``paused`` / ``excluded`` / ``error``)
# are used as the stable ``key``; these labels are the ``display_name``.
_STATUS_DISPLAY_LABELS = {
    STATUS_NORMAL: "正常",
    STATUS_IDLE: "空闲",
    STATUS_PAUSED: "已暂停",
    STATUS_EXCLUDED: "已排除",
    "error": "异常",
}

_UNKNOWN_APP_LABEL = "未知应用"
_UNKNOWN_STATUS_LABEL = "未知状态"


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
        # ``_live_projection`` only returns a virtual (unpersisted normal)
        # snapshot, so ``live["status"]`` is always STATUS_NORMAL. idle /
        # paused / excluded / error snapshots are never projected (item 13).
        live_duration = int(live["duration_seconds"])
        total += live_duration
        effective += live_duration
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
    """Project the current unpersisted normal snapshot as live time.

    Unified live-display model. Only a *virtual* snapshot (normal,
    unpersisted, no persisted_activity_id) is projected. idle / paused /
    excluded / error snapshots are NEVER projected as normal project
    live duration. persisted_open snapshots are NEVER projected here
    because their real DB row already carries the live seconds via
    ``timeline_service._live_duration_for_row`` (avoiding double count).

    The projected duration includes the short-activity carry seconds so
    consecutive <30s activities do not first lose seconds and then
    suddenly jump when the next activity persists.
    """
    from .live_display_service import (
        short_activity_carry_seconds,
        classify_live_state,
        is_live_eligible_for_normal,
    )

    snapshot = _read_current_activity_snapshot()
    if not snapshot:
        return None
    report_date = timeline_service.get_default_report_date()
    # Only virtual (unpersisted normal) snapshots are eligible. This
    # excludes idle / paused / excluded / error (item 13) and
    # persisted_open (avoid double count with the real DB row).
    if classify_live_state(snapshot) != "virtual":
        return None
    if not is_live_eligible_for_normal(snapshot, report_date, report_date):
        return None
    if not (start_date <= report_date <= end_date):
        return None
    duration = snapshot_elapsed_seconds(snapshot) + snapshot_extra_seconds(snapshot)
    if duration <= 0:
        return None
    # Include the short-activity carry seconds so consecutive <30s
    # activities do not first lose seconds and then suddenly jump.
    duration = duration + short_activity_carry_seconds(snapshot, report_date)
    project = str(snapshot.get("inferred_project_name") or UNCATEGORIZED_PROJECT).strip() or UNCATEGORIZED_PROJECT
    description = ""
    if project != UNCATEGORIZED_PROJECT:
        from . import project_service

        existing = project_service.get_project_by_name(project)
        description = str((existing or {}).get("description") or "")
    return {
        "status": STATUS_NORMAL,
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


# --- Phase 4A: read-only statistics / export preview ---------------------
#
# ``get_statistics_export_summary`` is a READ-ONLY aggregation used by the
# WebView Statistics / Export page. It never writes to the DB, never writes a
# file, and never opens a save dialog. It only reads closed activities via
# ``timeline_service.get_report_activity_rows`` (which already excludes
# ``is_deleted = 1`` and, with ``include_hidden=False``, ``is_hidden = 1``).
#
# In-progress activities (``end_time IS NULL``) are excluded: they have no
# finalized duration. This matches the documented Phase 4A semantics and is
# locked by tests. The legacy Tkinter Statistics page projects the live
# snapshot via ``include_live=True``; Phase 4A intentionally does NOT project
# live time so the read-only preview is stable and deterministic.
#
# Status inclusion semantics (Phase 4A.1, documented and locked by tests):
#   - ``normal``  → included
#   - ``idle``    → included
#   - ``paused``  → included
#   - ``excluded``→ included
#   - ``error``   → included
#   All closed, non-hidden, non-deleted activities are aggregated regardless
#   of status. The ``by_status`` breakdown surfaces each status group with a
#   display label so the user can see how time was spent across states.
#
# The payload is display-safe: it contains only aggregated numbers and
# display names (project name, app name, status label). Raw ``window_title``,
# ``file_path_hint``, ``full_path``, ``clipboard``, ``note``, SQL, and
# tracebacks are never surfaced.


def get_statistics_export_summary(date_from: str, date_to: str) -> dict:
    """Return a read-only statistics + export-preview payload for a date range.

    Inputs are ``YYYY-MM-DD`` strings. ``date_from`` must be on or before
    ``date_to`` and the inclusive span must not exceed
    ``STATISTICS_SUMMARY_MAX_RANGE_DAYS`` calendar days. Violations raise
    ``ValueError`` (the API layer maps these to stable error codes).

    Non-string inputs (including ``None`` and ``bool``) are rejected as
    ``invalid_date``. ``bool`` is rejected explicitly because it is not a
    date string even though it is a subclass of ``int``.

    The returned dict is display-safe and contains no raw DB rows.
    """
    _validate_summary_date_range(date_from, date_to)
    rows = timeline_service.get_report_activity_rows(
        date_from,
        date_to,
        include_hidden=False,
        ensure_context=True,
    )
    # Only closed activities have a finalized duration. ``is_in_progress`` is
    # set by the timeline service before it projects an open activity's
    # ``end_time``, so this flag is reliable regardless of the projected
    # ``end_time`` value.
    closed_rows = [row for row in rows if not row.get("is_in_progress")]

    total_duration = 0
    all_activity_ids: set[int] = set()
    by_project: dict[str, dict] = {}
    by_app: dict[str, dict] = {}
    by_status: dict[str, dict] = {}

    for row in closed_rows:
        duration = int(row.get("report_duration_seconds") or row.get("duration_seconds") or 0)
        total_duration += duration
        activity_id = int(row.get("id") or 0)
        if activity_id:
            all_activity_ids.add(activity_id)

        project_name = str(row.get("report_project_name") or row.get("display_project_name") or UNCATEGORIZED_PROJECT).strip() or UNCATEGORIZED_PROJECT
        app_name = str(row.get("app_name") or "").strip() or _UNKNOWN_APP_LABEL
        status_code = str(row.get("status") or "").strip()
        status_label = _STATUS_DISPLAY_LABELS.get(status_code, _UNKNOWN_STATUS_LABEL)

        _accumulate_summary_group(by_project, project_name, project_name, duration, activity_id)
        _accumulate_summary_group(by_app, app_name, app_name, duration, activity_id)
        _accumulate_summary_group(by_status, status_code or "unknown", status_label, duration, activity_id)

    activity_count = len(all_activity_ids)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "total_duration_seconds": total_duration,
        "activity_count": activity_count,
        "project_count": len(by_project),
        "app_count": len(by_app),
        "by_project": _build_summary_groups(by_project, total_duration),
        "by_app": _build_summary_groups(by_app, total_duration),
        "by_status": _build_summary_groups(by_status, total_duration),
        "export_preview": {
            "date_from": date_from,
            "date_to": date_to,
            "included_activity_count": activity_count,
            "included_duration_seconds": total_duration,
            # Phase 4B: CSV export is now available. Excel / PDF /
            # timesheet are intentionally NOT listed here; the frontend must
            # never offer a format the backend cannot produce.
            "available_formats": ["csv"],
            "export_actions_enabled": True,
        },
    }


def validate_statistics_date_range(date_from: str, date_to: str) -> None:
    """Validate the date range shared by the Statistics summary and CSV export.

    This is the single canonical validation used by both the read-only
    summary (``get_statistics_export_summary``) and the Phase 4B CSV export
    (``export_service.build_statistics_csv_rows`` / ``write_statistics_csv``)
    so summary and export enforce identical rules.

    Raises ``ValueError`` with a stable code token (``invalid_date`` /
    ``invalid_range`` / ``range_too_large``) so the API layer can map to
    user-facing messages without echoing internal details. ``bool`` is
    rejected explicitly because it is not a date string even though it is
    a subclass of ``int``.
    """
    # ``bool`` is a subclass of ``int`` but not of ``str``; the ``str``
    # isinstance check below rejects it so ``True`` / ``False`` never reach
    # ``date.fromisoformat``.
    if not isinstance(date_from, str) or not isinstance(date_to, str):
        raise ValueError("invalid_date")
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError:
        raise ValueError("invalid_date")
    if start > end:
        raise ValueError("invalid_range")
    if (end - start).days > STATISTICS_SUMMARY_MAX_RANGE_DAYS - 1:
        raise ValueError("range_too_large")


# Backwards-compatible private alias. Existing internal callers and tests
# that referenced the pre-refactor private name keep working; the canonical
# implementation is the public ``validate_statistics_date_range`` above.
_validate_summary_date_range = validate_statistics_date_range


def get_status_display_label(status_code: str | None) -> str:
    """Return the display-safe Chinese label for a status code.

    Shared by the read-only statistics summary and the Phase 4B CSV export
    so both surface identical status labels. Unknown codes fall back to
    ``"未知状态"``; raw ``window_title`` / ``file_path_hint`` / ``note`` are
    never used.
    """
    return _STATUS_DISPLAY_LABELS.get(
        str(status_code or "").strip(), _UNKNOWN_STATUS_LABEL
    )


def _accumulate_summary_group(
    groups: dict[str, dict],
    key: str,
    display_name: str,
    duration: int,
    activity_id: int,
) -> None:
    group = groups.setdefault(
        key,
        {"display_name": display_name, "duration_seconds": 0, "activity_ids": set()},
    )
    group["duration_seconds"] += duration
    if activity_id:
        group["activity_ids"].add(activity_id)


def _build_summary_groups(groups: dict[str, dict], total_duration: int) -> list[dict]:
    items: list[dict] = []
    for key, group in groups.items():
        duration = int(group["duration_seconds"])
        percentage = round(duration / total_duration * 100, 1) if total_duration > 0 else 0.0
        items.append(
            {
                "key": key,
                "display_name": str(group["display_name"]),
                "duration_seconds": duration,
                "activity_count": len(group["activity_ids"]),
                "percentage": percentage,
            }
        )
    items.sort(key=lambda item: (-item["duration_seconds"], str(item["display_name"]).casefold()))
    return items
