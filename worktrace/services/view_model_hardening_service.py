"""Cross-surface hardening adapter over the canonical page ViewModels."""

from __future__ import annotations

from typing import Any

from ..constants import STATUS_NORMAL
from ..formatters import format_duration
from . import page_revision_service, view_model_service
from .activity_display_model_service import build_activity_display_model
from .report_projection_identity import stable_json_hash
from .report_revision_service import get_report_structure_revision
from .settings_service import get_bool_setting, get_int_setting, get_setting


def _apply_structure_revision(
    payload: dict[str, Any], *, report_date: str, today: str
) -> None:
    payload["structure_revision"] = get_report_structure_revision(report_date)
    page_revision_service.apply_page_revision(
        payload,
        report_date=report_date,
        today=today,
    )


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    payload = view_model_service.get_overview_view_model(today)
    scoped_today = str(payload.get("date") or today or "")
    from .report_projection_snapshot_service import build_visible_snapshot

    snapshot = build_visible_snapshot(scoped_today, scoped_today)
    standalone = [
        dict(entry)
        for entry in snapshot.standalone_status_entries
        if not bool(entry.get("is_in_progress"))
    ]

    # Status-only excluded intervals contribute to canonical totals but are
    # intentionally absent from Recent. Timeline is their anonymous view.
    payload["activities"] = list(payload.get("activities") or [])[:20]

    extra = sum(int(row.get("duration_seconds") or 0) for row in standalone)
    total = int(payload.get("today_total_seconds") or 0) + extra
    payload["today_total_seconds"] = total
    payload["today_total_base_seconds"] = int(
        payload.get("today_total_base_seconds") or 0
    ) + extra
    kpi_base = dict(payload.get("kpi_live_base") or {})
    kpi_base["today_total_seconds"] = int(
        kpi_base.get("today_total_seconds") or 0
    ) + extra
    payload["kpi_live_base"] = kpi_base

    concrete_projects = {
        int(row.get("report_project_id") or row.get("project_id") or 0)
        for row in snapshot.final_contributions
        if bool(row.get("is_report_project"))
        and int(row.get("report_project_id") or row.get("project_id") or 0) > 0
        and not bool(row.get("report_project_is_deleted"))
    }
    overview = dict(payload.get("overview") or {})
    overview.update(
        {
            "today_total_seconds": total,
            "total_duration": format_duration(total),
            "project_count": len(concrete_projects),
        }
    )
    payload["overview"] = overview
    _apply_structure_revision(
        payload, report_date=scoped_today, today=scoped_today
    )
    return payload


def _enable_safe_open_edit(entry: dict[str, Any]) -> None:
    if not bool(entry.get("is_in_progress")):
        entry.setdefault("can_edit_project", bool(entry.get("editable", True)))
        entry.setdefault("can_edit_note", bool(entry.get("editable", True)))
        entry.setdefault("can_edit_duration", bool(entry.get("editable", True)))
        return
    safe = (
        str(entry.get("status_code") or entry.get("status") or "")
        == STATUS_NORMAL
        and int(entry.get("open_activity_id") or 0) > 0
        and str(entry.get("row_kind") or "project_session")
        == "project_session"
    )
    entry.update(
        {
            "can_edit_project": safe,
            "can_edit_note": safe,
            "can_edit_duration": False,
            "editable": safe,
            "edit_disabled": not safe,
            "disable_reason": "" if safe else "进行中记录暂不支持编辑",
        }
    )
    for key in (
        "can_hide",
        "can_merge_previous",
        "can_merge_next",
        "can_split",
        "can_copy",
        "can_hide_activity",
    ):
        entry[key] = False


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    payload = view_model_service.get_timeline_view_model(report_date)
    for entry in payload.get("entries") or []:
        _enable_safe_open_edit(entry)
    scoped_date = str(payload.get("date") or report_date or "")
    today = view_model_service.timeline_service.get_default_report_date()
    _apply_structure_revision(payload, report_date=scoped_date, today=today)
    return payload


def get_session_activity_summary_view_model(**kwargs) -> dict[str, Any]:
    payload = view_model_service.get_session_activity_summary_view_model(**kwargs)
    scoped_date = str(payload.get("date") or kwargs.get("report_date") or "")
    today = view_model_service.timeline_service.get_default_report_date()
    _apply_structure_revision(payload, report_date=scoped_date, today=today)
    return payload


def get_refresh_state_view_model(report_date: str | None = None) -> dict[str, Any]:
    """Build heartbeat state without constructing the canonical projection."""

    snapshot = view_model_service._get_current_activity_snapshot()
    collector_status = get_setting("collector_status", "stopped") or "stopped"
    health = get_setting("collector_health_state", "stopped") or "stopped"
    paused = get_bool_setting("user_paused", False) or collector_status == "paused"
    today = view_model_service.timeline_service.get_default_report_date()
    scoped_date = report_date or today
    model = build_activity_display_model(
        report_date=today, today=today, snapshot=snapshot
    )
    live_clock = model.get("live_clock") or {}
    current_activity = model.get("current_activity") or {}
    live_revision = page_revision_service.live_revision(current_activity, live_clock)
    structure_revision = get_report_structure_revision(scoped_date)
    page_revision = stable_json_hash(
        [structure_revision, live_revision if scoped_date == today else ""]
    )
    if paused:
        status_display = "已暂停"
    elif collector_status == "running":
        status_display = (
            "记录中，刚才采集短暂异常"
            if health == "degraded"
            else "采集可能中断，请重试"
            if health == "failing"
            else "记录中"
        )
    elif collector_status == "error":
        status_display = "状态异常"
    else:
        status_display = "采集器未运行"
    persisted_id = int(current_activity.get("activity_id") or 0)
    return {
        "ok": True,
        "collector_status": collector_status,
        "collector_health_state": health,
        "collector_last_successful_observation_at": get_setting(
            "collector_last_successful_observation_at", ""
        )
        or "",
        "collector_consecutive_failures": get_int_setting(
            "collector_consecutive_failures", 0
        ),
        "paused": paused,
        "status_display": status_display,
        "current_activity_key": str(
            current_activity.get("stable_live_key")
            or live_clock.get("stable_live_key")
            or ""
        ),
        "current_activity_status": str(
            current_activity.get("status") or live_clock.get("live_state") or ""
        ),
        "is_persisted": bool(current_activity.get("is_persisted")),
        "persisted_activity_id": persisted_id,
        "live_revision": live_revision,
        "structure_revision": structure_revision,
        "page_revision": page_revision,
        "today": today,
        "report_date": scoped_date,
        "latest_activity_id": persisted_id,
        "live_clock": live_clock,
        "display_span_id": str(live_clock.get("display_span_id") or ""),
        "activity_display_model": model,
        "live_started_at_epoch_ms": int(live_clock.get("live_started_at_epoch_ms") or 0),
        "carry_seconds": int(live_clock.get("carry_seconds") or 0),
        "duration_seconds_at_sample": int(live_clock.get("duration_seconds_at_sample") or 0),
        "stable_live_key": str(live_clock.get("stable_live_key") or ""),
        "stable_live_key_hash": str(live_clock.get("stable_live_key_hash") or ""),
        "live_state": str(live_clock.get("live_state") or ""),
        "is_live": bool(live_clock.get("is_live")),
        "is_project_duration_live": bool(live_clock.get("is_project_duration_live")),
        "project_duration_live": bool(
            live_clock.get("project_duration_live", live_clock.get("is_project_duration_live"))
        ),
        "current_duration_live": bool(live_clock.get("current_duration_live")),
        "current_activity": current_activity,
        "sample_id": str(model.get("sample_id") or ""),
    }


__all__ = [
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
