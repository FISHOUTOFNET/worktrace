from __future__ import annotations

import json
from datetime import date, timedelta

from ..constants import STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED, UNCATEGORIZED_PROJECT
from .context_service import recompute_context_assignments_for_date
from . import timeline_service
from .live_display_service import (
    build_live_projection,
    classify_live_state,
    is_live_eligible_for_normal,
)
from .settings_service import get_setting

# Maximum inclusive calendar-day span accepted by the read-only
# statistics/export summary. A 31-day span (e.g. 2026-06-01..2026-07-01) is
# allowed; anything wider is rejected as ``range_too_large`` so the summary
# never reads an unbounded amount of data.
STATISTICS_SUMMARY_MAX_RANGE_DAYS = 31

# Display-safe Chinese labels for the by_status breakdown. The raw status
# codes (``normal`` / ``idle`` / ``paused`` / ``excluded`` / ``error``) are
# used as the stable ``key``; these labels are the ``display_name``.
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
    if live is not None and live.get("live_state") == "virtual":
        live_duration = int(live["duration_seconds"])
        total += live_duration
        effective += live_duration
    # Use include_live=True for project_stats so BOTH the virtual projection
    # (add duration to display_project group) AND the persisted_open overlay
    # (relabel matching session's project to display_project) are applied.
    # This keeps the uncategorized / classified split consistent with the
    # display_project contract during the 30-second pending window.
    project_stats = get_project_stats(start_date, end_date, ensure_context=False, include_live=include_live)
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


def get_project_stats(start_date: str, end_date: str, ensure_context: bool = True, include_live: bool = False) -> list[dict]:
    if ensure_context:
        _ensure_context_range(start_date, end_date)
    # Build the live projection once so we can apply BOTH:
    # - virtual: add the live duration to the display_project group
    # - persisted_open: relabel the matching session's project to
    #   display_project (no duration change — the DB row already carries it)
    live = _live_projection(start_date, end_date) if include_live else None
    persisted_overlay = _persisted_open_overlay(live)
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
        description = str(session.get("project_description") or "").strip()
        # Persisted_open overlay: when the session contains the
        # persisted_activity_id, relabel its project to the snapshot's
        # display_project (duration unchanged — see ``get_summary``).
        # open row's time to the inherited display project during the
        # 30-second pending window, NOT the DB row's candidate assignment.
        # The duration is NOT changed (no double-count).
        if persisted_overlay and persisted_overlay["persisted_activity_id"] in {
            int(aid) for aid in (session.get("activity_ids") or []) if aid
        }:
            project = str(persisted_overlay.get("project") or UNCATEGORIZED_PROJECT)
            description = str(persisted_overlay.get("project_description") or "").strip()
        group = groups.setdefault(project, {"project": project, "total_duration": 0, "record_count": 0})
        if description and not group.get("project_description"):
            group["project_description"] = description
        group["total_duration"] += int(session.get("duration_seconds") or 0)
        group["record_count"] += 1
    # Virtual live projection: add the live duration to the
    # display_project group. The virtual snapshot has no DB row, so no
    # double-count risk here (see ``get_summary``).
    if live is not None and live.get("live_state") == "virtual" and live.get("status") == STATUS_NORMAL:
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
    """Project the current live snapshot for KPI attribution."""
    snapshot = _read_current_activity_snapshot()
    if not snapshot:
        return None
    report_date = timeline_service.get_default_report_date()
    if not is_live_eligible_for_normal(snapshot, report_date, report_date):
        return None
    if not (start_date <= report_date <= end_date):
        return None
    live_state = classify_live_state(snapshot)
    if live_state not in {"virtual", "persisted_open"}:
        return None
    # Use the public live projection contract so virtual and persisted_open
    # share the SAME display_project source.
    projection = build_live_projection(snapshot, report_date=report_date, today=report_date)
    if not projection:
        return None
    duration = int(projection.get("duration_seconds") or 0)
    if duration <= 0:
        return None
    return {
        "live_state": live_state,
        "status": STATUS_NORMAL,
        "duration_seconds": duration,
        "project": str(projection.get("project_name") or UNCATEGORIZED_PROJECT),
        "project_description": str(projection.get("project_description") or ""),
        "is_uncategorized": bool(projection.get("is_uncategorized")),
        "persisted_activity_id": int(projection.get("persisted_activity_id") or 0),
    }


def _persisted_open_overlay(live: dict | None) -> dict | None:
    """Return the persisted_open project overlay info from a live projection.

    Returns ``None`` when ``live`` is ``None`` or the live state is not
    ``persisted_open``. Otherwise returns a dict with
    ``persisted_activity_id``, ``project``, ``project_description`` so the
    caller can relabel the matching session's project attribution to the
    snapshot's ``display_project`` without changing the duration.
    double-count).
    """
    if not live:
        return None
    if live.get("live_state") != "persisted_open":
        return None
    persisted_id = int(live.get("persisted_activity_id") or 0)
    if persisted_id <= 0:
        return None
    return {
        "persisted_activity_id": persisted_id,
        "project": str(live.get("project") or UNCATEGORIZED_PROJECT),
        "project_description": str(live.get("project_description") or ""),
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
            # CSV export is available. Excel / PDF / timesheet are
            # intentionally NOT listed here; the frontend must never offer
            # a format the backend cannot produce.
            "available_formats": ["csv"],
            "export_actions_enabled": True,
        },
    }


def validate_statistics_date_range(date_from: str, date_to: str) -> None:
    """Validate the date range shared by the Statistics summary and CSV export.

    This is the single canonical validation used by both the read-only
    summary (``get_statistics_export_summary``) and the CSV export
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


# Private alias for internal callers.
# that referenced the pre-refactor private name keep working; the canonical
# implementation is the public ``validate_statistics_date_range`` above.
_validate_summary_date_range = validate_statistics_date_range


def get_status_display_label(status_code: str | None) -> str:
    """Return the display-safe Chinese label for a status code.

    Shared by the read-only statistics summary and the CSV export so both
    surface identical status labels. Unknown codes fall back to
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
