"""Lightweight refresh-state ViewModel owner.

This path deliberately avoids canonical report projection construction. It
combines one atomic runtime sample with the generation-cached structural
revision used to decide whether a page payload must be refreshed.
"""

from __future__ import annotations

from typing import Any

from . import page_revision_service, timeline_service
from .activity_display_model_service import build_activity_display_model
from .report_projection_identity import stable_json_hash
from .report_revision_service import get_report_structure_revision
from .runtime_activity_state_service import get_runtime_activity_snapshot
from .settings_service import get_bool_setting, get_int_setting, get_setting


def get_refresh_state_view_model(
    report_date: str | None = None,
) -> dict[str, Any]:
    snapshot = get_runtime_activity_snapshot()
    collector_status = get_setting("collector_status", "stopped") or "stopped"
    health = get_setting("collector_health_state", "stopped") or "stopped"
    paused = get_bool_setting("user_paused", False) or collector_status == "paused"
    today = timeline_service.get_default_report_date()
    scoped_date = report_date or today
    model = build_activity_display_model(
        report_date=today,
        today=today,
        snapshot=snapshot,
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
            "collector_last_successful_observation_at",
            "",
        )
        or "",
        "collector_consecutive_failures": get_int_setting(
            "collector_consecutive_failures",
            0,
        ),
        "paused": paused,
        "status_display": status_display,
        "current_activity_key": str(
            current_activity.get("stable_live_key")
            or live_clock.get("stable_live_key")
            or ""
        ),
        "current_activity_status": str(
            current_activity.get("status")
            or live_clock.get("live_state")
            or ""
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
        "live_started_at_epoch_ms": int(
            live_clock.get("live_started_at_epoch_ms") or 0
        ),
        "carry_seconds": int(live_clock.get("carry_seconds") or 0),
        "duration_seconds_at_sample": int(
            live_clock.get("duration_seconds_at_sample") or 0
        ),
        "stable_live_key": str(live_clock.get("stable_live_key") or ""),
        "stable_live_key_hash": str(
            live_clock.get("stable_live_key_hash") or ""
        ),
        "live_state": str(live_clock.get("live_state") or ""),
        "is_live": bool(live_clock.get("is_live")),
        "is_project_duration_live": bool(
            live_clock.get("is_project_duration_live")
        ),
        "project_duration_live": bool(
            live_clock.get(
                "project_duration_live",
                live_clock.get("is_project_duration_live"),
            )
        ),
        "current_duration_live": bool(
            live_clock.get("current_duration_live")
        ),
        "current_activity": current_activity,
        "sample_id": str(model.get("sample_id") or ""),
    }


__all__ = ["get_refresh_state_view_model"]
