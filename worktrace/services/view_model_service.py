"""ViewModel constructor — sole owner of page display payloads.

This service is the ONLY place that assembles the display ViewModel for the
Overview, Recent, Timeline, Details, and Refresh-State pages. Every business
semantic that the frontend renders — live display, virtual live row,
persisted_open overlay, pending project transition, duration override, raw
duration, display project, candidate project, stable live key, live clock
fields — is constructed here.

Boundary rules:

- This service lives in ``worktrace.services`` so it may import other
  services (``live_display_service``, ``timeline_service``,
  ``statistics_service``, ``project_service``, ``settings_service``) and
  stdlib only. It MUST NOT be imported by ``worktrace.webview_ui.*``
  directly — the bridge layer reaches it through
  ``worktrace.api.view_model_api``.
- All payloads are JSON-serializable. Raw ``window_title``,
  ``file_path_hint``, clipboard text, SQL, tracebacks, full local paths,
  and passphrases are NEVER surfaced.
- Overview / Recent / Timeline / Details / Refresh State for the same
  current snapshot use a consistent ``live_projection``,
  ``stable_live_key_hash``, ``live_started_at_epoch_ms``, and
  ``carry_seconds`` (single-sample contract).
"""

from __future__ import annotations

import json
from typing import Any

from ..formatters import format_duration, format_resource_type, format_safe_display_name
from . import live_display_service, project_service, statistics_service, timeline_service
from .live_display_service import (
    apply_persisted_open_overlay_to_row,
    build_current_activity_summary,
    build_live_projection,
    build_persisted_open_overlay,
    build_virtual_detail_row,
    build_virtual_session,
    compute_refresh_revision,
)
from .settings_service import get_bool_setting, get_setting

# Maximum number of recent activities in the Overview VM.
_RECENT_LIMIT = 20


# Snapshot access helpers


def _get_current_activity_snapshot() -> dict[str, Any] | None:
    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _get_collector_status() -> str:
    return get_setting("collector_status", "stopped") or "stopped"


def _is_user_paused() -> bool:
    return get_bool_setting("user_paused", False)


# Overview ViewModel


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    """Build the complete Overview page ViewModel from a single snapshot.

    Reads the current activity snapshot exactly once and derives Overview
    KPIs, current activity, recent activities, live_projection, and
    sample_id from that single sample (no multi-sample drift).
    """
    scoped_today = today or timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    live_projection = build_live_projection(
        snapshot, report_date=scoped_today, today=scoped_today
    )
    live_display = build_current_activity_summary(
        snapshot, report_date=scoped_today, today=scoped_today
    )
    summary = statistics_service.get_summary(scoped_today, scoped_today, include_live=True)
    project_count = len(project_service.list_active_projects())
    sessions = timeline_service.get_project_sessions_by_date(
        scoped_today, include_hidden=False, ensure_context=True
    )
    persisted_overlay = build_persisted_open_overlay(
        snapshot, report_date=scoped_today, today=scoped_today
    )

    items: list[dict[str, Any]] = []
    if live_display.get("is_virtual_live"):
        virtual = build_virtual_session(
            snapshot, report_date=scoped_today, today=scoped_today
        )
        if virtual:
            items.append(
                {
                    "project_name": str(virtual.get("project_name") or "未归类"),
                    "project_description": str(virtual.get("project_description") or ""),
                    "start_time": str(virtual.get("start_time") or ""),
                    "end_time": "",
                    "duration": str(virtual.get("duration") or "00:00:00"),
                    "duration_seconds": int(virtual.get("duration_seconds") or 0),
                    "is_in_progress": True,
                    "is_live_projected": True,
                    "is_virtual": True,
                    "is_virtual_live": True,
                    "live_display_key": str(virtual.get("live_display_key") or ""),
                    "stable_live_key": str(virtual.get("stable_live_key") or ""),
                    "stable_live_key_hash": str(virtual.get("stable_live_key_hash") or ""),
                    "live_state": "virtual",
                    "live_started_at_epoch_ms": int(virtual.get("live_started_at_epoch_ms") or 0),
                    "carry_seconds": int(virtual.get("carry_seconds") or 0),
                    "disable_reason": str(virtual.get("disable_reason") or ""),
                    "activity_id": 0,
                    "source": "snapshot",
                    "edit_disabled": True,
                    "status": "进行中",
                }
            )
    for session in sessions[:_RECENT_LIMIT]:
        base_seconds = int(session.get("duration_seconds") or 0)
        is_in_progress = bool(session.get("is_in_progress"))
        row = {
            "project_name": str(session.get("project_name") or "未归类"),
            "project_description": str(session.get("project_description") or ""),
            "start_time": str(session.get("start_time") or ""),
            "end_time": str(session.get("end_time") or ""),
            "duration": format_duration(base_seconds),
            "duration_seconds": base_seconds,
            "is_in_progress": is_in_progress,
            "is_live_projected": is_in_progress,
            "is_virtual": False,
            "is_virtual_live": False,
            "live_display_key": "",
            "live_state": "",
            "stable_live_key": "",
            "stable_live_key_hash": "",
            "live_started_at_epoch_ms": 0,
            "carry_seconds": 0,
            "activity_id": int(session.get("first_activity_id") or 0) or 0,
            "source": "db",
            "edit_disabled": False,
            "disable_reason": "",
            "status": str(session.get("status_summary") or session.get("status") or ""),
        }
        apply_persisted_open_overlay_to_row(row, persisted_overlay)
        items.append(row)

    total_seconds = int(summary.get("total_duration") or 0)
    classified_seconds = int(summary.get("classified_duration") or 0)
    uncategorized_seconds = int(summary.get("uncategorized_duration") or 0)
    sample_id = str(live_projection.get("stable_live_key_hash") or "")
    elapsed = int(live_display.get("elapsed_seconds") or 0)

    return {
        "ok": True,
        "date": scoped_today,
        "sample_id": sample_id,
        "live_projection": live_projection,
        "live_display": live_display,
        "overview": {
            "total_duration": format_duration(total_seconds),
            "classified_duration": format_duration(classified_seconds),
            "uncategorized_duration": format_duration(uncategorized_seconds),
            "project_count": project_count,
            "today_total_seconds": total_seconds,
            "classified_seconds": classified_seconds,
            "uncategorized_seconds": uncategorized_seconds,
        },
        "current_activity": live_display,
        "activities": items,
        "today_total_seconds": total_seconds,
        "classified_seconds": classified_seconds,
        "uncategorized_seconds": uncategorized_seconds,
        "current_activity_elapsed_seconds": elapsed,
    }


# Timeline ViewModel


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    """Build the complete Timeline page ViewModel from a single snapshot.

    Today's view may inject a virtual live session; historical dates do not.
    The persisted_open overlay covers display project / live identity.
    In-progress rows are always ``edit_disabled=True``. Duration overrides
    do not modify the raw duration.
    """
    scoped_report_date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    sessions_raw = timeline_service.get_project_sessions_by_date(
        scoped_report_date, include_hidden=False, ensure_context=True
    )
    snapshot = _get_current_activity_snapshot()
    live_display = build_current_activity_summary(
        snapshot, report_date=scoped_report_date, today=today
    )
    live_projection = build_live_projection(
        snapshot, report_date=scoped_report_date, today=today
    )
    persisted_overlay = build_persisted_open_overlay(
        snapshot, report_date=scoped_report_date, today=today
    )
    is_today = scoped_report_date == today

    sessions: list[dict[str, Any]] = []
    display_total_seconds = 0
    raw_total_seconds = 0

    if is_today:
        virtual_session = build_virtual_session(
            snapshot, report_date=scoped_report_date, today=today
        )
        if virtual_session is not None:
            virtual_seconds = int(virtual_session.get("duration_seconds") or 0)
            display_total_seconds += virtual_seconds
            raw_total_seconds += virtual_seconds
            sessions.append(
                {
                    "session_id": str(virtual_session.get("session_id") or ""),
                    "project_name": str(virtual_session.get("project_name") or "未归类"),
                    "project_description": str(virtual_session.get("project_description") or ""),
                    "project_id": int(virtual_session.get("project_id") or 0),
                    "start_time": str(virtual_session.get("start_time") or ""),
                    "end_time": "",
                    "duration": str(virtual_session.get("duration") or "00:00:00"),
                    "duration_seconds": virtual_seconds,
                    "raw_duration": str(virtual_session.get("duration") or "00:00:00"),
                    "raw_duration_seconds": virtual_seconds,
                    "adjusted_duration_seconds": None,
                    "has_duration_override": False,
                    "status": str(virtual_session.get("status") or "进行中"),
                    "event_count": 1,
                    "is_uncategorized": bool(virtual_session.get("is_uncategorized")),
                    "is_classified": bool(virtual_session.get("is_classified")),
                    "is_in_progress": True,
                    "is_live_projected": False,
                    "is_virtual": True,
                    "is_virtual_live": True,
                    "live_display_key": str(virtual_session.get("live_display_key") or ""),
                    "live_state": "virtual",
                    "stable_live_key": str(virtual_session.get("stable_live_key") or ""),
                    "stable_live_key_hash": str(virtual_session.get("stable_live_key_hash") or ""),
                    "live_started_at_epoch_ms": int(virtual_session.get("live_started_at_epoch_ms") or 0),
                    "carry_seconds": int(virtual_session.get("carry_seconds") or 0),
                    "activity_ids": [],
                    "first_activity_id": None,
                    "session_note": "",
                    "edit_disabled": True,
                    "disable_reason": str(virtual_session.get("disable_reason") or ""),
                    "source": "snapshot",
                    "display_project": virtual_session.get("display_project"),
                    "candidate_project": virtual_session.get("candidate_project"),
                    "project_transition": virtual_session.get("project_transition"),
                    "project_transition_pending": bool(virtual_session.get("project_transition_pending")),
                }
            )

    for session in sessions_raw:
        is_session_in_progress = bool(session.get("is_in_progress"))
        start_time = str(session.get("start_time") or "")
        raw_seconds = int(session.get("raw_duration_seconds") or session.get("duration_seconds") or 0)
        adjusted = session.get("adjusted_duration_seconds")
        if adjusted is not None:
            adjusted = int(adjusted)
        has_override = adjusted is not None
        display_seconds = adjusted if has_override else raw_seconds
        display_total_seconds += display_seconds
        raw_total_seconds += raw_seconds
        row = {
            "session_id": str(session.get("session_id") or ""),
            "project_name": str(session.get("project_name") or "未归类"),
            "project_description": str(session.get("project_description") or ""),
            "project_id": int(session.get("project_id") or 0),
            "start_time": start_time,
            "end_time": str(session.get("end_time") or ""),
            "duration": format_duration(display_seconds),
            "duration_seconds": display_seconds,
            "raw_duration": format_duration(raw_seconds),
            "raw_duration_seconds": raw_seconds,
            "adjusted_duration_seconds": adjusted,
            "has_duration_override": has_override,
            "status": str(session.get("status_summary") or session.get("status") or ""),
            "event_count": int(session.get("event_count") or 0),
            "is_uncategorized": bool(session.get("is_uncategorized")),
            "is_classified": not bool(session.get("is_uncategorized")),
            "is_in_progress": is_session_in_progress,
            "is_live_projected": False,
            "is_virtual": False,
            "is_virtual_live": False,
            "live_display_key": "",
            "live_state": "",
            "stable_live_key": "",
            "stable_live_key_hash": "",
            "live_started_at_epoch_ms": 0,
            "carry_seconds": 0,
            "activity_ids": list(session.get("activity_ids") or []),
            "first_activity_id": int(session.get("first_activity_id") or 0) or None,
            "session_note": str(session.get("session_note") or ""),
            "edit_disabled": False,
            "disable_reason": "",
            "source": "db",
            "display_project": None,
            "candidate_project": None,
            "project_transition": None,
            "project_transition_pending": False,
        }
        apply_persisted_open_overlay_to_row(row, persisted_overlay)
        if is_session_in_progress and not row.get("edit_disabled"):
            row["edit_disabled"] = True
            row["disable_reason"] = row.get("disable_reason") or "进行中记录暂不支持编辑"
        sessions.append(row)

    elapsed = int(live_display.get("elapsed_seconds") or 0)
    sample_id = str(live_projection.get("stable_live_key_hash") or "")

    return {
        "ok": True,
        "date": scoped_report_date,
        "total_duration": format_duration(display_total_seconds),
        "total_seconds": display_total_seconds,
        "raw_total_duration": format_duration(raw_total_seconds),
        "raw_total_seconds": raw_total_seconds,
        "current_activity": live_display,
        "live_display": live_display,
        "live_projection": live_projection,
        "sample_id": sample_id,
        "sessions": sessions,
        "today_total_seconds": display_total_seconds,
        "current_activity_elapsed_seconds": elapsed,
    }


# Session Details ViewModel


def get_session_details_view_model(
    activity_ids: list[int],
    report_date: str | None = None,
) -> dict[str, Any]:
    """Build the complete Timeline Details ViewModel from a single snapshot.

    Covers the virtual detail row, persisted_open overlay, display-safe
    resource/project fields, edit_disabled/disable_reason, duration_seconds,
    live clock fields, and the single-sample live_display/live_projection
    contract.
    """
    ids = [int(aid) for aid in (activity_ids or [])]
    date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    live_display = build_current_activity_summary(
        snapshot, report_date=date, today=today
    )
    detail_live_projection = build_live_projection(
        snapshot, report_date=date, today=today
    )
    persisted_overlay = build_persisted_open_overlay(
        snapshot, report_date=date, today=today
    )
    activities: list[dict[str, Any]] = []

    if not ids:
        virtual_row = build_virtual_detail_row(
            snapshot, report_date=date, today=today
        )
        if virtual_row is not None:
            activities.append(
                {
                    "activity_id": 0,
                    "start_time": str(virtual_row.get("start_time") or ""),
                    "end_time": "",
                    "duration": str(virtual_row.get("duration") or "00:00:00"),
                    "duration_seconds": int(virtual_row.get("duration_seconds") or 0),
                    "app_name": str(virtual_row.get("app_name") or ""),
                    "resource_type": str(virtual_row.get("resource_type") or ""),
                    "resource_name": str(virtual_row.get("resource_name") or "未知"),
                    "project_name": str(virtual_row.get("project_name") or "未归类"),
                    "project_description": str(virtual_row.get("project_description") or ""),
                    "status": str(virtual_row.get("status") or ""),
                    "is_in_progress": True,
                    "is_live_projected": True,
                    "is_virtual": True,
                    "is_virtual_live": True,
                    "live_display_key": str(virtual_row.get("live_display_key") or ""),
                    "stable_live_key": str(virtual_row.get("stable_live_key") or ""),
                    "stable_live_key_hash": str(virtual_row.get("stable_live_key_hash") or ""),
                    "live_state": "virtual",
                    "live_started_at_epoch_ms": int(virtual_row.get("live_started_at_epoch_ms") or 0),
                    "carry_seconds": int(virtual_row.get("carry_seconds") or 0),
                    "source": "snapshot",
                    "edit_disabled": True,
                    "disable_reason": str(virtual_row.get("disable_reason") or ""),
                }
            )
        sample_id = str(detail_live_projection.get("stable_live_key_hash") or "")
        return {
            "ok": True,
            "activities": activities,
            "live_display": live_display,
            "live_projection": detail_live_projection,
            "sample_id": sample_id,
        }

    rows = timeline_service.get_session_activity_details(
        ids, report_date=date, ensure_context=True
    )
    for row in rows:
        start_time = str(row.get("start_time") or "")
        end_time = str(row.get("end_time") or "")
        row_seconds = int(row.get("duration_seconds") or 0)
        is_in_progress = bool(row.get("is_in_progress"))
        detail_row = {
            "activity_id": int(row.get("id") or 0),
            "start_time": start_time,
            "end_time": end_time,
            "duration": format_duration(row_seconds),
            "duration_seconds": row_seconds,
            "app_name": str(row.get("app_name") or ""),
            "resource_type": format_resource_type(
                row.get("resource_kind"), row.get("resource_subtype")
            ),
            "resource_name": format_safe_display_name(row),
            "project_name": str(row.get("project_name") or "未归类"),
            "project_description": str(row.get("project_description") or ""),
            "status": str(row.get("status") or ""),
            "is_in_progress": is_in_progress,
            "is_live_projected": is_in_progress,
            "is_virtual": False,
            "is_virtual_live": False,
            "live_display_key": "",
            "live_state": "",
            "stable_live_key": "",
            "stable_live_key_hash": "",
            "live_started_at_epoch_ms": 0,
            "carry_seconds": 0,
            "source": "db",
            "edit_disabled": False,
            "disable_reason": "",
        }
        apply_persisted_open_overlay_to_row(detail_row, persisted_overlay)
        if is_in_progress and not detail_row.get("edit_disabled"):
            detail_row["edit_disabled"] = True
            detail_row["disable_reason"] = detail_row.get("disable_reason") or "进行中记录暂不支持编辑"
        activities.append(detail_row)

    sample_id = str(detail_live_projection.get("stable_live_key_hash") or "")
    return {
        "ok": True,
        "activities": activities,
        "live_display": live_display,
        "live_projection": detail_live_projection,
        "sample_id": sample_id,
    }


# Refresh State ViewModel


def get_refresh_state_view_model(report_date: str | None = None) -> dict[str, Any]:
    """Build the heartbeat / refresh-state ViewModel from a single snapshot.

    Refresh revision, collector display status, live clock fields, stable
    live identity, and report date scope are all constructed here.
    """
    snapshot = _get_current_activity_snapshot()
    collector_status = _get_collector_status()
    user_paused = _is_user_paused()
    paused = bool(user_paused) or collector_status == "paused"
    today = timeline_service.get_default_report_date()
    scoped_report_date = report_date or today

    refresh_revision, debug_inputs = compute_refresh_revision(
        snapshot, collector_status, user_paused, today, scoped_report_date
    )
    current_activity_key = str(debug_inputs.get("current_activity_key") or "")
    current_activity_status = str(debug_inputs.get("current_status") or "")
    is_persisted = bool(debug_inputs.get("is_persisted"))
    persisted_activity_id = int(debug_inputs.get("persisted_id") or 0)
    inferred_project_name = str(debug_inputs.get("inferred_project") or "")
    latest_activity_id = int(debug_inputs.get("latest_id") or 0)

    live_summary = build_current_activity_summary(
        snapshot, report_date=scoped_report_date, today=today
    )

    if paused or collector_status == "paused":
        status_display = "已暂停"
    elif collector_status == "running":
        status_display = "记录中"
    elif collector_status == "error":
        status_display = "状态异常"
    else:
        status_display = "采集器未运行"

    return {
        "ok": True,
        "collector_status": collector_status,
        "paused": paused,
        "status_display": status_display,
        "current_activity_key": current_activity_key,
        "current_activity_status": current_activity_status,
        "is_persisted": is_persisted,
        "persisted_activity_id": persisted_activity_id,
        "inferred_project_name": inferred_project_name,
        "refresh_revision": refresh_revision,
        "today": today,
        "report_date": scoped_report_date,
        "latest_activity_id": latest_activity_id,
        "live_started_at_epoch_ms": int(live_summary.get("live_started_at_epoch_ms") or 0),
        "carry_seconds": int(live_summary.get("carry_seconds") or 0),
        "stable_live_key": str(live_summary.get("stable_live_key") or ""),
        "stable_live_key_hash": str(live_summary.get("stable_live_key_hash") or ""),
        "live_state": str(live_summary.get("live_state") or ""),
    }


__all__ = [
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_details_view_model",
    "get_timeline_view_model",
]
