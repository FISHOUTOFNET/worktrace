"""Page ViewModel constructor — projects the unified Activity Display Model.

Assembles the page-level ViewModel for Overview / Recent / Timeline /
Details / Refresh-State. Owns NO live-display semantics: every live
semantic (live clock, display span identity, ``<30s`` pending absorption,
persisted_open overlay, project transition) is decided by
:mod:`worktrace.services.activity_display_model_service`. This module only:

1. Calls :func:`build_activity_display_model` once per request.
2. Projects page payloads from that model.
3. Builds ordinary DB list payloads (sessions, activity details).
4. Applies ``apply_live_span_to_row`` to matching DB rows.
5. Materializes an unanchored ``virtual_pending`` span as display-only
   Recent / Timeline / Detail rows.

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


def _get_virtual_pending_span(model: dict[str, Any]) -> dict[str, Any] | None:
    span = get_live_span(model)
    if not span:
        return None
    if str(span.get("live_state") or "") != "virtual_pending":
        return None
    if int(span.get("anchor_activity_id") or 0) != 0:
        return None
    return span


def _display_only_common_fields(span: dict[str, Any]) -> dict[str, Any]:
    live_clock = span.get("live_clock") or {}
    duration_seconds = int(span.get("duration_seconds") or 0)
    return {
        "activity_id": int(span.get("activity_id") or 0),
        "start_time": str(span.get("start_time") or ""),
        "end_time": "",
        "duration": format_duration(duration_seconds),
        "duration_seconds": duration_seconds,
        "raw_duration_seconds": 0,
        "live_base_seconds": duration_seconds,
        "live_delta_eligible": True,
        "is_in_progress": True,
        "is_live_projected": True,
        "is_virtual": True,
        "is_virtual_live": True,
        "is_display_only": True,
        "display_only": True,
        "editable": False,
        "exportable": False,
        "source": "snapshot",
        "edit_disabled": True,
        "disable_reason": str(span.get("disable_reason") or ""),
        "display_span_id": str(span.get("display_span_id") or ""),
        "stable_live_key": str(live_clock.get("stable_live_key") or ""),
        "stable_live_key_hash": str(live_clock.get("stable_live_key_hash") or ""),
        "live_state": str(live_clock.get("live_state") or ""),
        "live_started_at_epoch_ms": int(live_clock.get("live_started_at_epoch_ms") or 0),
        "carry_seconds": int(live_clock.get("carry_seconds") or 0),
        "duration_seconds_at_sample": int(live_clock.get("duration_seconds_at_sample") or 0),
        "is_live": bool(live_clock.get("is_live")),
        "is_project_duration_live": bool(live_clock.get("is_project_duration_live")),
        "project_id": int(span.get("project_id") or 0),
        "project_name": str(span.get("project_name") or "未归类"),
        "project_description": str(span.get("project_description") or ""),
        "display_project": span.get("display_project"),
        "candidate_project": span.get("candidate_project"),
        "project_transition": span.get("project_transition"),
        "project_transition_pending": bool(span.get("project_transition_pending")),
        "is_uncategorized": bool(span.get("is_uncategorized")),
        "is_classified": bool(span.get("is_classified")),
    }


def _materialize_display_only_recent_row(span: dict[str, Any]) -> dict[str, Any]:
    row = _display_only_common_fields(span)
    row.update(
        {
            "project_name": str(span.get("project_name") or "未归类"),
            "project_description": str(span.get("project_description") or ""),
            "activity_ids": [int(span.get("activity_id") or 0)],
            "first_activity_id": int(span.get("activity_id") or 0),
            "status": "进行中",
        }
    )
    return row


def _materialize_display_only_timeline_session(span: dict[str, Any]) -> dict[str, Any]:
    row = _display_only_common_fields(span)
    stable_hash = str(row.get("stable_live_key_hash") or "")
    row.update(
        {
            "session_id": "live:" + stable_hash if stable_hash else "live:pending",
            "activity_ids": [int(span.get("activity_id") or 0)],
            "first_activity_id": int(span.get("activity_id") or 0),
            "raw_duration": format_duration(0),
            "adjusted_duration_seconds": None,
            "has_duration_override": False,
            "status": "进行中",
            "event_count": 1,
            "session_note": "",
        }
    )
    return row


def _materialize_display_only_detail_row(
    span: dict[str, Any],
    current_activity: dict[str, Any],
) -> dict[str, Any]:
    row = _display_only_common_fields(span)
    row.update(
        {
            "app_name": str(current_activity.get("app_name") or ""),
            "resource_type": format_resource_type(
                current_activity.get("resource_kind"),
                current_activity.get("resource_subtype"),
            ),
            "resource_name": str(span.get("resource_name") or "未知"),
            "status": str(current_activity.get("status") or "normal"),
        }
    )
    return row


# Overview ViewModel


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    """Build the Overview page ViewModel from a single display model.

    Recent activities come ONLY from DB sessions; the unified live span is
    applied as an overlay onto the matching DB row (persisted_open /
    absorbed_pending). A ``<30s`` pending resource with no anchor does NOT
    inject a virtual recent item — it only appears in the current-activity
    area.

    KPI totals (``today_total_seconds`` / ``classified_seconds`` /
    ``uncategorized_seconds``) are computed from the SAME overlaid sessions
    list so the KPI, recent items, and live clock all share one sample.

    Single-sample contract: ``current_activity_snapshot`` is read EXACTLY
    ONCE here and passed to :func:`build_activity_display_model`; the builder
    MUST NOT re-read the setting on this path.
    """
    scoped_today = today or timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    model = build_activity_display_model(
        report_date=scoped_today, today=scoped_today, snapshot=snapshot
    )
    live_clock = model.get("live_clock") or {}
    current_activity_clock = model.get("current_activity_clock") or {}
    current_activity = model.get("current_activity") or {}
    display_span_id = str(live_clock.get("display_span_id") or "")

    project_count = len(project_service.list_active_projects())
    sessions = timeline_service.get_project_sessions_by_date(
        scoped_today, include_hidden=False, ensure_context=True
    )

    # Build row dicts for ALL sessions (used for KPI computation).
    all_rows: list[dict[str, Any]] = []
    for session in sessions:
        all_rows.append(_session_to_overview_row(session))
    # Apply the unified live-span overlay to ALL session rows so the KPI
    # totals reflect the same sample as the recent items.
    _apply_live_span_to_rows(all_rows, model)
    virtual_span = _get_virtual_pending_span(model)
    if virtual_span and virtual_span.get("is_visible_in_recent"):
        all_rows.insert(0, _materialize_display_only_recent_row(virtual_span))

    # KPI totals computed from the overlaid rows. Classification uses the
    # explicit ``is_classified`` / ``is_uncategorized`` flags propagated by
    # ``_session_to_overview_row``; a missing field MUST NOT silently fall
    # back to the classified bucket (no falsy-default behavior).
    today_total_seconds = sum(int(r.get("duration_seconds") or 0) for r in all_rows)
    classified_seconds = sum(
        int(r.get("duration_seconds") or 0)
        for r in all_rows
        if bool(r.get("is_classified"))
    )
    uncategorized_seconds = sum(
        int(r.get("duration_seconds") or 0)
        for r in all_rows
        if bool(r.get("is_uncategorized"))
    )

    # Recent items are the first N overlaid rows.
    items = all_rows[:_RECENT_LIMIT]

    sample_id = str(model.get("sample_id") or "")
    elapsed = int(current_activity.get("elapsed_seconds") or 0)

    return {
        "ok": True,
        "date": scoped_today,
        "sample_id": sample_id,
        "display_span_id": display_span_id,
        "live_clock": live_clock,
        "current_activity_clock": current_activity_clock,
        "activity_display_model": model,
        "overview": {
            "total_duration": format_duration(today_total_seconds),
            "classified_duration": format_duration(classified_seconds),
            "uncategorized_duration": format_duration(uncategorized_seconds),
            "project_count": project_count,
            "today_total_seconds": today_total_seconds,
            "classified_seconds": classified_seconds,
            "uncategorized_seconds": uncategorized_seconds,
        },
        "current_activity": current_activity,
        "activities": items,
        "today_total_seconds": today_total_seconds,
        "classified_seconds": classified_seconds,
        "uncategorized_seconds": uncategorized_seconds,
        "current_activity_elapsed_seconds": elapsed,
        # KPI live-base fields for the frontend ticker: the ticker renders
        # ``live_base_seconds + live_delta`` so the KPI ticks from the same
        # sample as the recent items.
        "kpi_live_base": {
            "today_total_seconds": today_total_seconds,
            "classified_seconds": classified_seconds,
            "uncategorized_seconds": uncategorized_seconds,
        },
    }


def _session_to_overview_row(session: dict[str, Any]) -> dict[str, Any]:
    """Project a timeline session dict into an Overview recent-item row.

    The classification flags (``project_id`` / ``is_uncategorized`` /
    ``is_classified``) MUST be propagated explicitly from the source
    session so the Overview KPI ``classified_seconds`` /
    ``uncategorized_seconds`` split is based on a positive field check
    rather than relying on a missing field's falsy default.

    ``activity_ids`` / ``first_activity_id`` MUST be propagated so
    ``apply_live_span_to_row`` can match a persisted_open anchor that is
    NOT the session's first activity (the common case when a closed
    activity precedes the open one in the same session). ``activity_id``
    stays equal to ``first_activity_id`` to preserve session identity;
    the live overlay matches via ``activity_ids`` membership, not via
    ``activity_id`` equality.
    """
    base_seconds = int(session.get("duration_seconds") or 0)
    is_in_progress = bool(session.get("is_in_progress"))
    is_uncategorized = bool(session.get("is_uncategorized"))
    first_activity_id = int(session.get("first_activity_id") or 0) or None
    return {
        "project_name": str(session.get("project_name") or "未归类"),
        "project_description": str(session.get("project_description") or ""),
        "project_id": int(session.get("project_id") or 0),
        "is_uncategorized": is_uncategorized,
        "is_classified": not is_uncategorized,
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
        "activity_ids": list(session.get("activity_ids") or []),
        "first_activity_id": first_activity_id,
        "activity_id": int(first_activity_id or 0),
        "source": "db",
        "edit_disabled": False,
        "disable_reason": "",
        "status": str(session.get("status_summary") or session.get("status") or ""),
    }


# Timeline ViewModel


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    """Build the Timeline page ViewModel from a single display model.

    Timeline sessions come ONLY from the DB. The unified live span is
    applied as an overlay onto the matching DB session (persisted_open /
    absorbed_pending) BEFORE computing the display total so the total
    matches the sum of the session rows. A ``<30s`` pending resource with
    no anchor does NOT inject a virtual session.

    ``raw_total_seconds`` is the sum of raw DB durations (unaffected by
    the display-only live overlay or adjusted overrides). ``total_seconds``
    / ``today_total_seconds`` use the display durations after overlay.

    Single-sample contract: ``current_activity_snapshot`` is read EXACTLY
    ONCE here and the resulting ``snapshot`` is passed to
    :func:`build_activity_display_model` (via ``snapshot=...``). The
    builder MUST NOT re-read the setting on this path.
    """
    scoped_report_date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    model = build_activity_display_model(
        report_date=scoped_report_date, today=today, snapshot=snapshot
    )
    live_clock = model.get("live_clock") or {}
    current_activity_clock = model.get("current_activity_clock") or {}
    current_activity = model.get("current_activity") or {}
    display_span_id = str(live_clock.get("display_span_id") or "")

    sessions_raw = timeline_service.get_project_sessions_by_date(
        scoped_report_date, include_hidden=False, ensure_context=True
    )

    sessions: list[dict[str, Any]] = []
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
    # Apply the unified live-span overlay to matching sessions BEFORE
    # computing the display total so the total matches the sum of rows.
    _apply_live_span_to_rows(sessions, model)
    virtual_span = _get_virtual_pending_span(model)
    if virtual_span and virtual_span.get("is_visible_in_timeline"):
        sessions.insert(0, _materialize_display_only_timeline_session(virtual_span))
    # In-progress sessions that received no live overlay still need
    # edit_disabled.
    for row in sessions:
        if row.get("is_in_progress") and not row.get("edit_disabled"):
            row["edit_disabled"] = True
            row["disable_reason"] = row.get("disable_reason") or "进行中记录暂不支持编辑"

    # display_total_seconds is the sum of display durations AFTER overlay.
    display_total_seconds = sum(int(r.get("duration_seconds") or 0) for r in sessions)

    elapsed = int(current_activity.get("elapsed_seconds") or 0)
    sample_id = str(model.get("sample_id") or "")

    return {
        "ok": True,
        "date": scoped_report_date,
        "total_duration": format_duration(display_total_seconds),
        "total_seconds": display_total_seconds,
        "raw_total_duration": format_duration(raw_total_seconds),
        "raw_total_seconds": raw_total_seconds,
        "current_activity": current_activity,
        "live_clock": live_clock,
        "current_activity_clock": current_activity_clock,
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

    Single-sample contract: ``current_activity_snapshot`` is read EXACTLY
    ONCE here and the resulting ``snapshot`` is passed to
    :func:`build_activity_display_model` (via ``snapshot=...``). The
    builder MUST NOT re-read the setting on this path.
    """
    ids = [int(aid) for aid in (activity_ids or [])]
    date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    model = build_activity_display_model(
        report_date=date, today=today, snapshot=snapshot
    )
    live_clock = model.get("live_clock") or {}
    current_activity_clock = model.get("current_activity_clock") or {}
    current_activity = model.get("current_activity") or {}
    display_span_id = str(live_clock.get("display_span_id") or "")
    sample_id = str(model.get("sample_id") or "")

    virtual_span = _get_virtual_pending_span(model)
    if virtual_span and virtual_span.get("is_visible_in_details"):
        virtual_id = int(virtual_span.get("activity_id") or 0)
        if not ids or virtual_id in ids:
            return {
                "ok": True,
                "activities": [
                    _materialize_display_only_detail_row(virtual_span, current_activity)
                ],
                "current_activity": current_activity,
                "live_clock": live_clock,
                "current_activity_clock": current_activity_clock,
                "display_span_id": display_span_id,
                "activity_display_model": model,
                "sample_id": sample_id,
            }

    if not ids:
        return {
            "ok": True,
            "activities": [],
            "current_activity": current_activity,
            "live_clock": live_clock,
            "current_activity_clock": current_activity_clock,
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
        "current_activity": current_activity,
        "live_clock": live_clock,
        "current_activity_clock": current_activity_clock,
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

    Single-sample contract: the ``current_activity_snapshot`` is read
    EXACTLY ONCE in this function and the resulting ``snapshot`` is passed
    to BOTH :func:`build_activity_display_model` (via ``snapshot=...``)
    AND :func:`compute_refresh_revision`. This guarantees the returned
    ``refresh_revision``, ``debug_inputs.current_activity_key``,
    ``live_clock``, ``current_activity``, and ``activity_display_model``
    all originate from the same sample — no double-read race.
    """
    snapshot = _get_current_activity_snapshot()
    collector_status = _get_collector_status()
    user_paused = _is_user_paused()
    paused = bool(user_paused) or collector_status == "paused"
    today = timeline_service.get_default_report_date()
    scoped_report_date = report_date or today

    # Pass the already-read snapshot into the display model so it does
    # NOT re-read the setting. ``refresh_revision`` and ``live_clock``
    # share the same sample.
    model = build_activity_display_model(
        report_date=scoped_report_date, today=today, snapshot=snapshot
    )
    live_clock = model.get("live_clock") or {}
    current_activity_clock = model.get("current_activity_clock") or {}
    current_activity = model.get("current_activity") or {}
    display_span_id = str(live_clock.get("display_span_id") or "")

    refresh_revision, debug_inputs = compute_refresh_revision(
        snapshot,
        collector_status,
        user_paused,
        today,
        scoped_report_date,
        display_model=model,
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
        "current_activity_clock": current_activity_clock,
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
        "current_activity": current_activity,
        "sample_id": str(model.get("sample_id") or ""),
    }


__all__ = [
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_details_view_model",
    "get_timeline_view_model",
]
