"""Page ViewModel constructor — projects the unified Activity Display Model.

Assembles the page-level ViewModel for Overview / Recent / Timeline /
Details / Refresh-State. Owns NO live-display semantics: every live
semantic (live clock, display span identity, ``<30s`` pending absorption,
persisted_open overlay, project transition) is decided by
:mod:`worktrace.services.activity_display_model_service`. This module only:

1. Calls :func:`build_activity_display_model` once per request.
2. Projects page payloads from that model.
3. Builds ordinary DB list payloads (sessions, activity details).
4. Applies ``apply_live_span_to_row`` to matching DB rows — NEVER injects a
   separate virtual recent item / virtual session / virtual detail row.

Boundary:

- Lives in ``worktrace.services``; imports ``activity_display_model_service``,
  ``live_display_service``, ``timeline_service``, ``statistics_service``,
  ``project_service``, ``settings_service`` and stdlib only. MUST NOT be
  imported by ``worktrace.webview_ui.*`` directly — bridge uses
  ``worktrace.api.view_model_api``.
- JSON-serializable only. Raw ``window_title`` / ``file_path_hint`` /
  clipboard / SQL / tracebacks / paths / passphrases NEVER surfaced.
- All page payloads for the same snapshot share the SAME ``live_clock`` /
  ``display_span_id`` / ``stable_live_key_hash`` /
  ``live_started_at_epoch_ms`` / ``carry_seconds``.
"""

from __future__ import annotations

import json
from typing import Any

from ..formatters import format_duration, format_resource_type, format_safe_display_name
from . import activity_display_model_service, live_display_service, project_service, statistics_service, timeline_service
from .activity_display_model_service import (
    apply_live_span_to_row,
    build_activity_display_model,
    get_live_span,
)
from .live_display_service import compute_refresh_revision
from .settings_service import get_bool_setting, get_setting

# Maximum number of recent activities in the Overview VM.
_RECENT_LIMIT = 20


# Snapshot / status access helpers


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


def _apply_live_span_to_rows(rows: list[dict[str, Any]], model: dict[str, Any]) -> None:
    """Apply the unified live-span overlay to every matching DB row.

    Mutates rows in place. Rows that do not match the live span's anchor
    activity id are left untouched. This is the ONLY path through which a
    live row enters Recent / Timeline / Details — there is no separate
    virtual-row injection anymore.
    """
    span = get_live_span(model)
    if not span:
        return
    for row in rows:
        apply_live_span_to_row(row, span)


# Overview ViewModel


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    """Build the Overview page ViewModel from a single display model.

    Recent activities come ONLY from DB sessions. The unified live span is
    applied as an overlay onto the matching DB row (persisted_open /
    absorbed_pending). A ``<30s`` pending resource with no anchor does NOT
    inject a virtual recent item — it only appears in the current-activity
    area.
    """
    scoped_today = today or timeline_service.get_default_report_date()
    model = build_activity_display_model(report_date=scoped_today, today=scoped_today)
    live_clock = model.get("live_clock") or {}
    live_projection = model.get("live_projection") or {}
    live_display = model.get("current_activity") or {}
    display_span_id = str(live_clock.get("display_span_id") or "")

    summary = statistics_service.get_summary(scoped_today, scoped_today, include_live=True)
    project_count = len(project_service.list_active_projects())
    sessions = timeline_service.get_project_sessions_by_date(
        scoped_today, include_hidden=False, ensure_context=True
    )

    items: list[dict[str, Any]] = []
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
            "display_span_id": "",
            "activity_id": int(session.get("first_activity_id") or 0) or 0,
            "source": "db",
            "edit_disabled": False,
            "disable_reason": "",
            "status": str(session.get("status_summary") or session.get("status") or ""),
        }
        items.append(row)
    # Apply the unified live-span overlay to matching rows only.
    _apply_live_span_to_rows(items, model)

    total_seconds = int(summary.get("total_duration") or 0)
    classified_seconds = int(summary.get("classified_duration") or 0)
    uncategorized_seconds = int(summary.get("uncategorized_duration") or 0)
    sample_id = str(model.get("sample_id") or live_projection.get("stable_live_key_hash") or "")
    elapsed = int(live_display.get("elapsed_seconds") or 0)

    return {
        "ok": True,
        "date": scoped_today,
        "sample_id": sample_id,
        "display_span_id": display_span_id,
        "live_clock": live_clock,
        "activity_display_model": model,
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
    """Build the Timeline page ViewModel from a single display model.

    Timeline sessions come ONLY from the DB. The unified live span is
    applied as an overlay onto the matching DB session (persisted_open /
    absorbed_pending). A ``<30s`` pending resource with no anchor does NOT
    inject a virtual session — it only appears in the current-activity
    area. The virtual seconds are NOT added to the timeline total anymore.
    """
    scoped_report_date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    model = build_activity_display_model(report_date=scoped_report_date, today=today)
    live_clock = model.get("live_clock") or {}
    live_projection = model.get("live_projection") or {}
    live_display = model.get("current_activity") or {}
    display_span_id = str(live_clock.get("display_span_id") or "")

    sessions_raw = timeline_service.get_project_sessions_by_date(
        scoped_report_date, include_hidden=False, ensure_context=True
    )

    sessions: list[dict[str, Any]] = []
    display_total_seconds = 0
    raw_total_seconds = 0

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
            "display_span_id": "",
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
        sessions.append(row)
    # Apply the unified live-span overlay to matching sessions only.
    _apply_live_span_to_rows(sessions, model)
    # In-progress sessions that received no live overlay still need
    # edit_disabled (legacy behaviour).
    for row in sessions:
        if row.get("is_in_progress") and not row.get("edit_disabled"):
            row["edit_disabled"] = True
            row["disable_reason"] = row.get("disable_reason") or "进行中记录暂不支持编辑"

    elapsed = int(live_display.get("elapsed_seconds") or 0)
    sample_id = str(model.get("sample_id") or live_projection.get("stable_live_key_hash") or "")

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
        "live_clock": live_clock,
        "display_span_id": display_span_id,
        "activity_display_model": model,
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
    """Build the Timeline Details ViewModel from a single display model.

    When ``activity_ids`` is empty, NO virtual detail row is injected
    anymore — the frontend renders the current-activity area only. When
    activity ids are present, the DB activity rows are listed and the
    unified live span is applied as an overlay onto the matching row
    (persisted_open / absorbed_pending).
    """
    ids = [int(aid) for aid in (activity_ids or [])]
    date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    model = build_activity_display_model(report_date=date, today=today)
    live_clock = model.get("live_clock") or {}
    live_projection = model.get("live_projection") or {}
    live_display = model.get("current_activity") or {}
    display_span_id = str(live_clock.get("display_span_id") or "")
    sample_id = str(model.get("sample_id") or live_projection.get("stable_live_key_hash") or "")

    if not ids:
        # No virtual detail row is injected for an empty selection. The
        # frontend uses the current-activity area from the display model.
        return {
            "ok": True,
            "activities": [],
            "live_display": live_display,
            "live_projection": live_projection,
            "live_clock": live_clock,
            "display_span_id": display_span_id,
            "activity_display_model": model,
            "sample_id": sample_id,
        }

    rows = timeline_service.get_session_activity_details(
        ids, report_date=date, ensure_context=True
    )
    activities: list[dict[str, Any]] = []
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
            "display_span_id": "",
            "source": "db",
            "edit_disabled": False,
            "disable_reason": "",
        }
        activities.append(detail_row)
    # Apply the unified live-span overlay to matching detail rows only.
    _apply_live_span_to_rows(activities, model)
    for detail_row in activities:
        if detail_row.get("is_in_progress") and not detail_row.get("edit_disabled"):
            detail_row["edit_disabled"] = True
            detail_row["disable_reason"] = detail_row.get("disable_reason") or "进行中记录暂不支持编辑"

    return {
        "ok": True,
        "activities": activities,
        "live_display": live_display,
        "live_projection": live_projection,
        "live_clock": live_clock,
        "display_span_id": display_span_id,
        "activity_display_model": model,
        "sample_id": sample_id,
    }


# Refresh State ViewModel


def get_refresh_state_view_model(report_date: str | None = None) -> dict[str, Any]:
    """Build the heartbeat / refresh-state ViewModel from a single display model.

    Refresh revision, collector display status, live clock fields, stable
    live identity, and report date scope are all derived from the unified
    display model so the frontend heartbeat can update the live registry
    without a full page-model refresh.
    """
    snapshot = _get_current_activity_snapshot()
    collector_status = _get_collector_status()
    user_paused = _is_user_paused()
    paused = bool(user_paused) or collector_status == "paused"
    today = timeline_service.get_default_report_date()
    scoped_report_date = report_date or today

    model = build_activity_display_model(report_date=scoped_report_date, today=today)
    live_clock = model.get("live_clock") or {}
    live_display = model.get("current_activity") or {}
    display_span_id = str(live_clock.get("display_span_id") or "")

    refresh_revision, debug_inputs = compute_refresh_revision(
        snapshot, collector_status, user_paused, today, scoped_report_date
    )
    current_activity_key = str(debug_inputs.get("current_activity_key") or "")
    current_activity_status = str(debug_inputs.get("current_status") or "")
    is_persisted = bool(debug_inputs.get("is_persisted"))
    persisted_activity_id = int(debug_inputs.get("persisted_id") or 0)
    inferred_project_name = str(debug_inputs.get("inferred_project") or "")
    latest_activity_id = int(debug_inputs.get("latest_id") or 0)

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
        # Unified live clock (single source of truth for the frontend).
        "live_clock": live_clock,
        "display_span_id": display_span_id,
        "activity_display_model": model,
        "live_started_at_epoch_ms": int(live_clock.get("live_started_at_epoch_ms") or 0),
        "carry_seconds": int(live_clock.get("carry_seconds") or 0),
        "duration_seconds_at_sample": int(live_clock.get("duration_seconds_at_sample") or 0),
        "stable_live_key": str(live_clock.get("stable_live_key") or ""),
        "stable_live_key_hash": str(live_clock.get("stable_live_key_hash") or ""),
        "live_state": str(live_clock.get("live_state") or ""),
        "is_live": bool(live_clock.get("is_live")),
        "is_project_duration_live": bool(live_clock.get("is_project_duration_live")),
        "current_activity": live_display,
        "live_display": live_display,
        "sample_id": str(model.get("sample_id") or ""),
    }


__all__ = [
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_details_view_model",
    "get_timeline_view_model",
]
