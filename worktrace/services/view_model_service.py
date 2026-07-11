"""Page ViewModel constructor — projects the unified Activity Display Model.

Assembles the page-level ViewModel for Overview / Recent / Timeline /
Details / Refresh-State. Owns NO live-display semantics: every live
semantic (live clock, display span identity, persisted-open overlay, project
transition) is decided by
:mod:`worktrace.services.activity_display_model_service`. This module only:

1. Calls :func:`build_activity_display_model` once per request.
2. Projects page payloads from that model.
3. Builds ordinary DB list payloads (sessions, activity details).
4. Applies ``apply_live_span_to_row`` to the matching persisted DB row when
   the display model marks that surface materializable.

Boundary:

- Lives in ``worktrace.services``; imports display-model modules,
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

from ..constants import UNCATEGORIZED_PROJECT
from ..formatters import format_duration, format_resource_type, format_safe_display_name
from ..contracts.live_display_contracts import (
    ActivitySnapshotContract,
    CurrentActivityContract,
    DisplaySpanContract,
    LiveClockContract,
    RefreshStateContract,
)
from . import (
    live_display_service,
    project_activity_summary_service,
    project_service,
    statistics_service,
    timeline_service,
)
from .activity_display_model_service import build_activity_display_model
from .activity_display_projection import build_kpi_live_targets
from .activity_continuity_service import is_normal_project_status
from .activity_row_overlay import (
    ROW_KIND_ACTIVITY_DETAIL_ROW,
    ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW,
    ROW_KIND_PROJECT_SESSION_ROW,
    ROW_KIND_RECENT_PROJECT_SESSION_ROW,
    apply_live_span_to_row,
)
from .live_display_service import compute_refresh_revision
from .settings_service import get_bool_setting, get_int_setting, get_setting

# Maximum number of recent activities in the Overview VM.
_RECENT_LIMIT = 20


# Snapshot / status access helpers


def _get_current_activity_snapshot() -> ActivitySnapshotContract | None:
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


def _get_collector_health_state() -> str:
    return get_setting("collector_health_state", "stopped") or "stopped"


def _is_user_paused() -> bool:
    return get_bool_setting("user_paused", False)


def _apply_live_span_to_rows(
    rows: list[dict[str, Any]],
    model: dict[str, Any],
    *,
    row_kind: str,
) -> None:
    """Apply the unified live-span overlay to every matching DB row.

    Mutates rows in place. Rows that do not match the live span's anchor
    activity id are left untouched. This is the ONLY path through which a
    live overlay enters Recent / Timeline / Details.
    """
    span = _first_display_span(model)
    if not span:
        return
    if row_kind == ROW_KIND_RECENT_PROJECT_SESSION_ROW:
        surface = "recent"
    elif row_kind == ROW_KIND_PROJECT_SESSION_ROW:
        surface = "timeline"
    elif row_kind == ROW_KIND_ACTIVITY_DETAIL_ROW:
        surface = "details"
    elif row_kind == ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW:
        surface = "details"
    else:
        surface = ""
    if surface and not span.get("is_visible_in_" + surface):
        return
    for row in rows:
        apply_live_span_to_row(row, span, row_kind=row_kind)


def _first_display_span(model: dict[str, Any]) -> DisplaySpanContract | None:
    spans = model.get("display_spans") or []
    return spans[0] if spans else None


def _set_summary_activity_ids(rows: list[dict[str, Any]]) -> None:
    """Attach read-only Timeline summary scope without changing session IDs."""
    for row in rows:
        ids = _unique_positive_ids(row.get("activity_ids") or [])
        if row.get("is_live_projected"):
            anchor_id = int(
                row.get("live_anchor_activity_id")
                or row.get("anchor_activity_id")
                or 0
            )
            if anchor_id > 0:
                ids = _unique_positive_ids([*ids, anchor_id])
        row["summary_activity_ids"] = ids


def _unique_positive_ids(values: list[Any]) -> list[int]:
    result: list[int] = []
    for value in values:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item > 0 and item not in result:
            result.append(item)
    return result


def _current_elapsed_at_sample(live_clock: LiveClockContract) -> int:
    return int(
        live_clock.get("current_elapsed_at_sample")
        or live_clock.get("active_elapsed_at_sample")
        or 0
    )


def _clock_projects_live_duration(live_clock: LiveClockContract) -> bool:
    return bool(
        live_clock.get("is_live")
        and (
            live_clock.get("project_duration_live") is True
            or live_clock.get("is_project_duration_live") is True
        )
    )


def _revision_fields_for_model(
    snapshot: dict[str, Any] | None,
    model: dict[str, Any],
    *,
    today: str,
    report_date: str,
) -> dict[str, str]:
    collector_status = _get_collector_status()
    user_paused = _is_user_paused()
    refresh_revision, debug_inputs = compute_refresh_revision(
        snapshot,
        collector_status,
        user_paused,
        today,
        report_date,
        display_model=model,
    )
    return {
        "refresh_revision": refresh_revision,
        "live_clock_revision": str(debug_inputs.get("live_clock_revision") or ""),
        "live_state_revision": str(debug_inputs.get("live_state_revision") or ""),
        "display_projection_revision": str(
            debug_inputs.get("display_projection_revision") or ""
        ),
        "page_structure_revision": str(debug_inputs.get("page_structure_revision") or ""),
    }


def _live_identity_fields(model: dict[str, Any]) -> dict[str, Any]:
    live_clock = model.get("live_clock") or {}
    return {
        "display_span_id": str(live_clock.get("display_span_id") or ""),
        "stable_live_key_hash": str(live_clock.get("stable_live_key_hash") or ""),
        "sample_id": str(model.get("sample_id") or ""),
    }


def _detail_report_project_dict(row: dict[str, Any]) -> dict[str, Any]:
    project_name = str(row.get("project_name") or UNCATEGORIZED_PROJECT)
    is_report_project = bool(row.get("is_report_project"))
    return {
        "id": int(row.get("project_id") or 0) or None,
        "name": project_name,
        "description": str(row.get("project_description") or ""),
        "source": str(row.get("report_attribution_kind") or "none"),
        "is_uncategorized": not is_report_project,
        "is_suggested_project": False,
    }


def _detail_candidate_project_dict(row: dict[str, Any]) -> dict[str, Any]:
    candidate_name = str(row.get("candidate_project_name") or "")
    if candidate_name:
        return {
            "id": None,
            "name": candidate_name,
            "description": "",
            "source": str(row.get("assignment_source") or "candidate"),
            "is_uncategorized": False,
            "is_suggested_project": True,
        }
    return _detail_report_project_dict(row)


def _detail_report_attribution_fields(row: dict[str, Any]) -> dict[str, Any]:
    is_report_project = bool(row.get("is_report_project"))
    is_report_classified = bool(row.get("is_report_classified", is_report_project))
    is_report_uncategorized = bool(row.get("is_report_uncategorized", not is_report_project))
    return {
        "project_id": int(row.get("project_id") or 0),
        "project_name": str(row.get("project_name") or UNCATEGORIZED_PROJECT),
        "project_description": str(row.get("project_description") or ""),
        "display_project": row.get("display_project") or _detail_report_project_dict(row),
        "candidate_project": row.get("candidate_project") or _detail_candidate_project_dict(row),
        "project_transition": row.get("project_transition"),
        "project_transition_pending": bool(row.get("project_transition_pending")),
        "is_uncategorized": bool(row.get("is_report_uncategorized", not is_report_project)),
        "is_classified": bool(row.get("is_report_classified", is_report_project)),
        "is_report_project": is_report_project,
        "is_report_classified": is_report_classified,
        "is_report_uncategorized": is_report_uncategorized,
        "report_attribution_kind": str(row.get("report_attribution_kind") or "none"),
        "is_official_project": bool(row.get("is_official_project")),
        "assignment_source": str(row.get("assignment_source") or ""),
        "project_attribution_kind": str(row.get("project_attribution_kind") or ""),
    }



# Overview ViewModel


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    """Build the Overview page ViewModel from a single display model.

    Live projection comes only from the Activity Display Model. Normal live
    activity materializes only its own persisted open row; it never borrows a
    closed anchor or creates a pending virtual row. Contract fallbacks remain
    display-only and do not represent short-activity absorption.

    KPI totals (``today_total_seconds`` / ``classified_seconds`` /
    ``uncategorized_seconds``) are computed from the same overlay +
    materialized rows so the KPI, recent items, and live clock share one
    sample.

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
    current_activity = model.get("current_activity") or {}
    identity_fields = _live_identity_fields(model)
    revision_fields = _revision_fields_for_model(
        snapshot,
        model,
        today=scoped_today,
        report_date=scoped_today,
    )

    project_count = len(project_service.list_active_projects())
    sessions = timeline_service.get_project_sessions_by_date(
        scoped_today, include_hidden=False, ensure_context=True
    )

    recent_rows: list[dict[str, Any]] = []
    for session in sessions:
        recent_rows.append(_session_to_overview_row(session))
    _apply_live_span_to_rows(
        recent_rows,
        model,
        row_kind=ROW_KIND_RECENT_PROJECT_SESSION_ROW,
    )
    status_display_item = model.get("status_display_item")
    if isinstance(status_display_item, dict):
        recent_rows.insert(0, dict(status_display_item))

    # KPI totals computed from the overlaid rows. Classification uses the
    # explicit ``is_classified`` / ``is_uncategorized`` flags propagated by
    # ``_session_to_overview_row``; a missing field MUST NOT silently fall
    # back to the classified bucket (no falsy-default behavior).
    total_rows = [r for r in recent_rows if r.get("contributes_to_totals") is not False]
    today_total_seconds = sum(int(r.get("duration_seconds") or 0) for r in total_rows)
    classified_seconds = sum(
        int(r.get("duration_seconds") or 0)
        for r in total_rows
        if bool(r.get("is_classified"))
    )
    uncategorized_seconds = sum(
        int(r.get("duration_seconds") or 0)
        for r in total_rows
        if bool(r.get("is_uncategorized"))
    )
    active_elapsed = _current_elapsed_at_sample(live_clock)
    live_projects = _clock_projects_live_duration(live_clock)
    today_total_base_seconds = (
        max(0, today_total_seconds - active_elapsed)
        if live_projects
        else today_total_seconds
    )
    classified_base_seconds = classified_seconds
    uncategorized_base_seconds = uncategorized_seconds
    live_span_id = str(live_clock.get("display_span_id") or "")
    live_total_rows = [
        r
        for r in total_rows
        if live_span_id
        and str(r.get("display_span_id") or "") == live_span_id
        and r.get("live_delta_eligible") is True
    ]
    live_row_is_classified = any(bool(r.get("is_classified")) for r in live_total_rows)
    live_row_is_uncategorized = any(bool(r.get("is_uncategorized")) for r in live_total_rows)
    if live_projects and live_row_is_classified:
        classified_base_seconds = max(0, classified_seconds - active_elapsed)
    if live_projects and live_row_is_uncategorized:
        uncategorized_base_seconds = max(0, uncategorized_seconds - active_elapsed)
    kpi_live_targets = build_kpi_live_targets(total_rows, live_clock)

    items = recent_rows[:_RECENT_LIMIT]

    elapsed = int(current_activity.get("elapsed_seconds") or 0)

    return {
        "ok": True,
        "date": scoped_today,
        **identity_fields,
        **revision_fields,
        "live_clock": live_clock,
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
        "today_total_base_seconds": today_total_base_seconds,
        "classified_base_seconds": classified_base_seconds,
        "uncategorized_base_seconds": uncategorized_base_seconds,
        "current_activity_elapsed_seconds": elapsed,
        # KPI live-base fields for the frontend ticker: the ticker renders
        # ``display_base_seconds + current_elapsed_now``.
        "kpi_live_base": {
            "today_total_seconds": today_total_base_seconds,
            "classified_seconds": classified_base_seconds,
            "uncategorized_seconds": uncategorized_base_seconds,
        },
        "kpi_live_targets": kpi_live_targets,
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
    is_report_project = bool(session.get("is_report_project", session.get("is_classified")))
    is_report_classified = bool(session.get("is_report_classified", is_report_project))
    is_report_uncategorized = bool(session.get("is_report_uncategorized", not is_report_project))
    first_activity_id = int(session.get("first_activity_id") or 0) or None
    return {
        "project_name": str(session.get("project_name") or "未归类"),
        "project_description": str(session.get("project_description") or ""),
        "project_id": int(session.get("project_id") or 0),
        "raw_assignment_project_id": int(session.get("raw_assignment_project_id") or 0),
        "raw_assignment_project_name": str(session.get("raw_assignment_project_name") or "未归类"),
        "row_kind": "project_session",
        "is_uncategorized": is_report_uncategorized,
        "is_classified": is_report_classified,
        "is_report_project": is_report_project,
        "is_report_classified": is_report_classified,
        "is_report_uncategorized": is_report_uncategorized,
        "report_attribution_kind": str(session.get("report_attribution_kind") or "none"),
        "is_official_project": bool(session.get("is_official_project")),
        "start_time": str(session.get("start_time") or ""),
        "end_time": str(session.get("end_time") or ""),
        "duration": format_duration(base_seconds),
        "duration_seconds": base_seconds,
        "display_duration_seconds": int(session.get("display_duration_seconds") or base_seconds),
        "raw_duration_seconds": int(session.get("raw_duration_seconds") or base_seconds),
        "duration_seconds_at_sample": base_seconds,
        "display_base_seconds": base_seconds,
        "live_base_seconds": base_seconds,
        "is_in_progress": is_in_progress,
        "is_live_projected": False,
        "is_virtual": False,
        "is_virtual_live": False,
        "contributes_to_totals": bool(session.get("contributes_to_totals", True)),
        "live_delta_eligible": False,
        "live_display_key": "",
        "live_state": "",
        "stable_live_key": "",
        "stable_live_key_hash": "",
        "live_started_at_epoch_ms": 0,
        "carry_seconds": 0,
        "display_span_id": "",
        "activity_ids": list(session.get("activity_ids") or []),
        "activity_member_hash": str(session.get("activity_member_hash") or ""),
        "anchor_activity_id": int(session.get("anchor_activity_id") or 0),
        "first_activity_id": first_activity_id,
        "activity_id": int(first_activity_id or 0),
        "open_activity_id": int(session.get("open_activity_id") or 0),
        "closed_duration_seconds": int(session.get("closed_duration_seconds") or 0),
        "source": "db",
        "editable": bool(session.get("editable", not is_in_progress)),
        "exportable": bool(session.get("exportable", not is_in_progress)),
        "edit_disabled": bool(is_in_progress),
        "disable_reason": "进行中记录暂不支持编辑" if is_in_progress else "",
        "status_code": str(session.get("status_code") or session.get("status") or "normal"),
        "display_status": str(
            session.get("display_status")
            or session.get("status_label")
            or session.get("status_summary")
            or ""
        ),
        "status": str(session.get("status") or "normal"),
        "status_summary": str(session.get("status_summary") or ""),
        "override_id": session.get("override_id"),
        "override_match_state": session.get("override_match_state"),
        "has_project_override": bool(session.get("has_project_override")),
        "has_duration_override": bool(session.get("has_duration_override")),
        "session_note": str(session.get("session_note") or ""),
    }


# Timeline ViewModel


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    """Build the Timeline page ViewModel from a single display model.

    Timeline sessions come from DB rows plus Activity Display Model projection.
    Normal live activity materializes only its own persisted open row; there
    are no borrowed-anchor or pending virtual sessions. Contract fallbacks do
    not represent short-activity absorption.

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
    report_model = build_activity_display_model(
        report_date=scoped_report_date,
        today=today,
        snapshot=snapshot,
    )
    live_model = (
        report_model
        if scoped_report_date == today
        else build_activity_display_model(report_date=today, today=today, snapshot=snapshot)
    )
    report_live_clock = report_model.get("live_clock") or {}
    live_clock = live_model.get("live_clock") or {}
    current_activity = live_model.get("current_activity") or {}
    identity_fields = _live_identity_fields(live_model)
    revision_fields = _revision_fields_for_model(
        snapshot,
        live_model,
        today=today,
        report_date=today,
    )

    sessions_raw = timeline_service.get_project_sessions_by_date(
        scoped_report_date, include_hidden=False, ensure_context=True
    )

    sessions: list[dict[str, Any]] = []
    raw_total_seconds = 0

    for session in sessions_raw:
        is_session_in_progress = bool(session.get("is_in_progress"))
        is_report_project = bool(session.get("is_report_project", session.get("is_classified")))
        is_report_classified = bool(session.get("is_report_classified", is_report_project))
        is_report_uncategorized = bool(session.get("is_report_uncategorized", not is_report_project))
        start_time = str(session.get("start_time") or "")
        raw_seconds = int(session.get("raw_duration_seconds") or session.get("duration_seconds") or 0)
        adjusted = session.get("adjusted_duration_seconds")
        if adjusted is not None:
            adjusted = int(adjusted)
        has_override = adjusted is not None
        display_seconds = int(session.get("display_duration_seconds") or session.get("duration_seconds") or (adjusted if has_override else raw_seconds))
        raw_total_seconds += raw_seconds
        row = {
            "session_id": str(session.get("session_id") or ""),
            "row_kind": "project_session",
            "project_name": str(session.get("project_name") or "未归类"),
            "project_description": str(session.get("project_description") or ""),
            "project_id": int(session.get("project_id") or 0),
            "raw_assignment_project_id": int(session.get("raw_assignment_project_id") or 0),
            "raw_assignment_project_name": str(session.get("raw_assignment_project_name") or "未归类"),
            "start_time": start_time,
            "end_time": str(session.get("end_time") or ""),
            "duration": format_duration(display_seconds),
            "duration_seconds": display_seconds,
            "raw_duration": format_duration(raw_seconds),
            "raw_duration_seconds": raw_seconds,
            "display_duration_seconds": display_seconds,
            "duration_seconds_at_sample": display_seconds,
            "display_base_seconds": display_seconds,
            "live_base_seconds": display_seconds,
            "adjusted_duration_seconds": adjusted,
            "has_duration_override": has_override,
            "status": str(session.get("status") or "normal"),
            "status_code": str(session.get("status_code") or session.get("status") or "normal"),
            "display_status": str(
                session.get("display_status")
                or session.get("status_label")
                or session.get("status_summary")
                or ""
            ),
            "status_summary": str(session.get("status_summary") or ""),
            "event_count": int(session.get("event_count") or 0),
            "is_uncategorized": is_report_uncategorized,
            "is_classified": is_report_classified,
            "is_report_project": is_report_project,
            "is_report_classified": is_report_classified,
            "is_report_uncategorized": is_report_uncategorized,
            "report_attribution_kind": str(session.get("report_attribution_kind") or "none"),
            "is_official_project": bool(session.get("is_official_project")),
            "is_in_progress": is_session_in_progress,
            "is_live_projected": False,
            "is_virtual": False,
            "is_virtual_live": False,
            "contributes_to_totals": bool(session.get("contributes_to_totals", True)),
            "live_delta_eligible": False,
            "live_display_key": "",
            "live_state": "",
            "stable_live_key": "",
            "stable_live_key_hash": "",
            "live_started_at_epoch_ms": 0,
            "carry_seconds": 0,
            "display_span_id": "",
            "activity_ids": list(session.get("activity_ids") or []),
            "activity_member_hash": str(session.get("activity_member_hash") or ""),
            "projection_instance_key": str(session.get("projection_instance_key") or ""),
            "projection_kind": str(session.get("projection_kind") or "base"),
            "operation_id": session.get("operation_id"),
            "operation_group_key": session.get("operation_group_key"),
            "origin_activity_member_hashes": list(session.get("origin_activity_member_hashes") or []),
            "operation_match_state": str(session.get("operation_match_state") or "active"),
            "can_hide": bool(session.get("can_hide")),
            "can_merge_previous": bool(session.get("can_merge_previous")),
            "can_merge_next": bool(session.get("can_merge_next")),
            "can_split": bool(session.get("can_split")),
            "can_copy": bool(session.get("can_copy")),
            "can_hide_activity": bool(session.get("can_hide_activity")),
            "anchor_activity_id": int(session.get("anchor_activity_id") or 0),
            "first_activity_id": int(session.get("first_activity_id") or 0) or None,
            "open_activity_id": int(session.get("open_activity_id") or 0),
            "closed_duration_seconds": int(session.get("closed_duration_seconds") or 0),
            "session_note": str(session.get("session_note") or ""),
            "override_id": session.get("override_id"),
            "override_match_state": session.get("override_match_state"),
            "has_project_override": bool(session.get("has_project_override")),
            "editable": bool(session.get("editable", not is_session_in_progress)),
            "exportable": bool(session.get("exportable", not is_session_in_progress)),
            "edit_disabled": bool(is_session_in_progress),
            "disable_reason": "进行中记录暂不支持编辑" if is_session_in_progress else "",
            "source": "db",
            "display_project": None,
            "candidate_project": None,
            "project_transition": None,
            "project_transition_pending": False,
        }
        sessions.append(row)
    _apply_live_span_to_rows(sessions, report_model, row_kind=ROW_KIND_PROJECT_SESSION_ROW)
    _set_summary_activity_ids(sessions)
    # In-progress sessions that received no live overlay still need
    # edit_disabled.
    for row in sessions:
        if row.get("is_in_progress") and not row.get("edit_disabled"):
            row["edit_disabled"] = True
            row["disable_reason"] = row.get("disable_reason") or "进行中记录暂不支持编辑"

    display_total_seconds = sum(int(r.get("duration_seconds") or 0) for r in sessions)
    active_elapsed = _current_elapsed_at_sample(report_live_clock)
    today_total_base_seconds = (
        max(0, display_total_seconds - active_elapsed)
        if _clock_projects_live_duration(report_live_clock)
        else display_total_seconds
    )

    elapsed = int(current_activity.get("elapsed_seconds") or 0)

    return {
        "ok": True,
        "date": scoped_report_date,
        "total_duration": format_duration(display_total_seconds),
        "total_seconds": display_total_seconds,
        "raw_total_duration": format_duration(raw_total_seconds),
        "raw_total_seconds": raw_total_seconds,
        "current_activity": current_activity,
        "live_clock": live_clock,
        **identity_fields,
        **revision_fields,
        "activity_display_model": live_model,
        "report_activity_display_model": report_model,
        "sessions": sessions,
        "today_total_seconds": display_total_seconds,
        "today_total_base_seconds": today_total_base_seconds,
        "current_activity_elapsed_seconds": elapsed,
    }


# Session Details ViewModel


def get_session_details_view_model(
    activity_ids: list[int],
    report_date: str | None = None,
) -> dict[str, Any]:
    """Build the Timeline Details ViewModel from a single display model.

    Details list only real DB activity rows plus Activity Display Model
    projection for a persisted open row. No borrowed pending resource or
    virtual normal-live detail row is inserted.

    Single-sample contract: ``current_activity_snapshot`` is read EXACTLY
    ONCE here and the resulting ``snapshot`` is passed to
    :func:`build_activity_display_model` (via ``snapshot=...``). The
    builder MUST NOT re-read the setting on this path.
    """
    ids = [int(aid) for aid in (activity_ids or [])]
    date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    report_model = build_activity_display_model(
        report_date=date, today=today, snapshot=snapshot
    )
    live_model = (
        report_model
        if date == today
        else build_activity_display_model(report_date=today, today=today, snapshot=snapshot)
    )
    live_clock = live_model.get("live_clock") or {}
    current_activity = live_model.get("current_activity") or {}
    identity_fields = _live_identity_fields(live_model)
    revision_fields = _revision_fields_for_model(
        snapshot,
        live_model,
        today=today,
        report_date=today,
    )

    if not ids:
        return {
            "ok": True,
            "date": date,
            "activities": [],
            "current_activity": current_activity,
            "live_clock": live_clock,
            **identity_fields,
            **revision_fields,
            "activity_display_model": live_model,
            "report_activity_display_model": report_model,
        }

    rows = [
        row
        for row in timeline_service.get_session_activity_details(
            ids, report_date=date, ensure_context=True
        )
        if is_normal_project_status(str(row.get("status") or ""))
    ]
    activities: list[dict[str, Any]] = []
    for row in rows:
        start_time = str(row.get("start_time") or "")
        end_time = str(row.get("end_time") or "")
        row_seconds = int(row.get("duration_seconds") or 0)
        is_in_progress = bool(row.get("is_in_progress"))
        detail_row = {
            "activity_id": int(row.get("id") or 0),
            "row_kind": "activity_detail",
            "start_time": start_time,
            "end_time": end_time,
            "duration": format_duration(row_seconds),
            "duration_seconds": row_seconds,
            "app_name": str(row.get("app_name") or ""),
            "resource_type": format_resource_type(
                row.get("resource_kind"), row.get("resource_subtype")
            ),
            "resource_name": format_safe_display_name(row),
            **_detail_report_attribution_fields(row),
            "status": str(row.get("status") or ""),
            "status_code": str(row.get("status") or "normal"),
            "display_status": str(row.get("display_status") or row.get("status_summary") or ""),
            "is_in_progress": is_in_progress,
            "is_live_projected": False,
            "is_virtual": False,
            "is_virtual_live": False,
            "contributes_to_totals": True,
            "live_delta_eligible": False,
            "live_display_key": "",
            "live_state": "",
            "stable_live_key": "",
            "stable_live_key_hash": "",
            "live_started_at_epoch_ms": 0,
            "carry_seconds": 0,
            "display_span_id": "",
            "source": "db",
            "editable": not is_in_progress,
            "exportable": not is_in_progress,
            "edit_disabled": bool(is_in_progress),
            "disable_reason": "进行中记录暂不支持编辑" if is_in_progress else "",
        }
        activities.append(detail_row)
    # Apply the unified live-span overlay to matching detail rows only.
    _apply_live_span_to_rows(activities, report_model, row_kind=ROW_KIND_ACTIVITY_DETAIL_ROW)
    for detail_row in activities:
        if detail_row.get("is_in_progress") and not detail_row.get("edit_disabled"):
            detail_row["edit_disabled"] = True
            detail_row["disable_reason"] = detail_row.get("disable_reason") or "进行中记录暂不支持编辑"

    return {
        "ok": True,
        "date": date,
        "activities": activities,
        "current_activity": current_activity,
        "live_clock": live_clock,
        **identity_fields,
        **revision_fields,
        "activity_display_model": live_model,
        "report_activity_display_model": report_model,
    }


def get_session_activity_summary_view_model(
    activity_ids: list[int] | None = None,
    report_date: str | None = None,
    projection_instance_key: str | None = None,
) -> dict[str, Any]:
    """Build the Timeline right-panel summary scoped by session activities."""
    ids = [int(aid) for aid in (activity_ids or [])]
    date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    report_model = build_activity_display_model(
        report_date=date, today=today, snapshot=snapshot
    )
    live_model = (
        report_model
        if date == today
        else build_activity_display_model(report_date=today, today=today, snapshot=snapshot)
    )
    live_clock = live_model.get("live_clock") or {}
    current_activity = live_model.get("current_activity") or {}
    identity_fields = _live_identity_fields(live_model)
    revision_fields = _revision_fields_for_model(
        snapshot,
        live_model,
        today=today,
        report_date=today,
    )

    if projection_instance_key:
        rows = project_activity_summary_service.get_projection_session_activity_summary(
            projection_instance_key, date, ensure_context=True
        )
    else:
        rows = project_activity_summary_service.get_session_activity_summary(
            ids, date, include_hidden=False, ensure_context=True
        )
    _apply_live_span_to_rows(
        rows,
        report_model,
        row_kind=ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW,
    )

    for row in rows:
        if row.get("is_in_progress") and not row.get("edit_disabled"):
            row["edit_disabled"] = True
            row["disable_reason"] = row.get("disable_reason") or "进行中记录暂不支持编辑"
        row["duration"] = format_duration(int(row.get("duration_seconds") or 0))
    rows.sort(key=lambda item: (-int(item.get("duration_seconds") or 0), str(item.get("activity_name") or "")))

    return {
        "ok": True,
        "date": date,
        "activity_ids": ids,
        "projection_instance_key": projection_instance_key or "",
        "summary_rows": rows,
        "current_activity": current_activity,
        "live_clock": live_clock,
        **identity_fields,
        **revision_fields,
        "activity_display_model": live_model,
        "report_activity_display_model": report_model,
    }


# Refresh State ViewModel


def get_refresh_state_view_model(report_date: str | None = None) -> RefreshStateContract:
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
    collector_health_state = _get_collector_health_state()
    collector_last_successful_observation_at = (
        get_setting("collector_last_successful_observation_at", "") or ""
    )
    collector_consecutive_failures = get_int_setting("collector_consecutive_failures", 0)
    user_paused = _is_user_paused()
    paused = bool(user_paused) or collector_status == "paused"
    today = timeline_service.get_default_report_date()
    requested_report_date = report_date or today
    scoped_report_date = today

    # Pass the already-read snapshot into the display model so it does
    # NOT re-read the setting. ``refresh_revision`` and ``live_clock``
    # share the same sample.
    model = build_activity_display_model(
        report_date=scoped_report_date,
        today=today,
        snapshot=snapshot,
    )
    live_clock = model.get("live_clock") or {}
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
    latest_activity_id = int(debug_inputs.get("latest_id") or 0)
    live_clock_revision = str(debug_inputs.get("live_clock_revision") or "")
    live_state_revision = str(debug_inputs.get("live_state_revision") or "")
    display_projection_revision = str(
        debug_inputs.get("display_projection_revision") or ""
    )
    page_structure_revision = str(debug_inputs.get("page_structure_revision") or "")

    if paused or collector_status == "paused":
        status_display = "已暂停"
    elif collector_status == "running":
        if collector_health_state == "degraded":
            status_display = "记录中，刚才采集短暂异常"
        elif collector_health_state == "failing":
            status_display = "采集可能中断，请重试"
        else:
            status_display = "记录中"
    elif collector_status == "error":
        status_display = "状态异常"
    else:
        status_display = "采集器未运行"

    return {
        "ok": True,
        "collector_status": collector_status,
        "collector_health_state": collector_health_state,
        "collector_last_successful_observation_at": collector_last_successful_observation_at,
        "collector_consecutive_failures": collector_consecutive_failures,
        "paused": paused,
        "status_display": status_display,
        "current_activity_key": current_activity_key,
        "current_activity_status": current_activity_status,
        "is_persisted": is_persisted,
        "persisted_activity_id": persisted_activity_id,
        "live_clock_revision": live_clock_revision,
        "live_state_revision": live_state_revision,
        "display_projection_revision": display_projection_revision,
        "page_structure_revision": page_structure_revision,
        "refresh_revision": refresh_revision,
        "today": today,
        "report_date": scoped_report_date,
        "requested_report_date": requested_report_date,
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
        "project_duration_live": bool(live_clock.get("project_duration_live", live_clock.get("is_project_duration_live"))),
        "current_duration_live": bool(live_clock.get("current_duration_live")),
        "current_activity": current_activity,
        "sample_id": str(model.get("sample_id") or ""),
    }


__all__ = [
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_session_details_view_model",
    "get_timeline_view_model",
]
