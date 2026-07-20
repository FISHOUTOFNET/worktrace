from __future__ import annotations

import hashlib
import json
from typing import Any

from ..contracts.live_display_contracts import (
    ActivitySnapshotContract,
    CurrentActivityContract,
    DisplaySpanContract,
    LiveClockContract,
)
from ..formatters import format_duration
from .activity_display_policy import DisplaySessionPolicy
from .activity_live_clock import current_resource_identity_hash
from .live_display_service import (
    _display_resource_name,
    _snapshot_display_project_fields,
    _stable_live_key_hash,
)
from .live_time_service import snapshot_persisted_id

LIVE_EDIT_DISABLE_REASON = "当前活动正在进行，暂不能编辑"


def build_current_activity_display(
    snapshot: ActivitySnapshotContract | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    summary: CurrentActivityContract,
    live_clock: LiveClockContract,
) -> CurrentActivityContract:
    """Attach the sole live-time DTO to static current-activity metadata."""

    del anchor, display_live_state
    display = dict(summary)
    display["live_clock"] = dict(live_clock)
    if not snapshot:
        return display
    identity_hash = current_resource_identity_hash(snapshot)
    if identity_hash:
        display["current_activity_display_span_id"] = "current:" + identity_hash
    return display


def build_display_structural_signature(
    snapshot: ActivitySnapshotContract | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    live_clock: LiveClockContract,
    current_activity: CurrentActivityContract,
    policy: DisplaySessionPolicy,
    report_date: str,
    today: str,
    is_today: bool,
) -> str:
    signature_payload = {
        "stable_live_key_hash": str(
            live_clock.get("stable_live_key_hash")
            or _stable_live_key_hash(snapshot)
        ),
        "display_live_state": display_live_state,
        "is_persisted": bool(snapshot and snapshot.get("is_persisted")),
        "persisted_activity_id": int(snapshot_persisted_id(snapshot) or 0)
        if snapshot
        else 0,
        "display_project": _signature_project_dict(
            current_activity.get("display_project")
        ),
        "project_live_span": {
            "display_span_id": str(live_clock.get("display_span_id") or ""),
            "anchor_activity_id": int(anchor.get("id") or 0) if anchor else 0,
            "materialize_recent": bool(policy.materialize_recent),
            "materialize_timeline": bool(policy.materialize_timeline),
            "materialize_details": bool(policy.materialize_details),
        },
        "display_policy": policy.to_dict(),
        "report_date": report_date,
        "today": today,
        "is_today": bool(is_today),
    }
    return json.dumps(signature_payload, sort_keys=True, ensure_ascii=False)


def source_for_state(state: str) -> str:
    return "db" if state == "persisted_open" else "none"


def build_display_span(
    snapshot: ActivitySnapshotContract | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    live_clock: LiveClockContract,
    summary: CurrentActivityContract,
    policy: DisplaySessionPolicy,
    report_date: str,
    today: str,
) -> DisplaySpanContract:
    del anchor, summary, report_date, today
    activity_id = (
        int(snapshot_persisted_id(snapshot) or 0)
        if display_live_state == "persisted_open"
        else 0
    )
    is_persisted = activity_id > 0
    project_fields = _snapshot_display_project_fields(snapshot)
    elapsed = int(live_clock["elapsed_seconds_at_sample"])
    aggregate_base = int(live_clock["aggregate_base_seconds"])
    semantic = str(live_clock["duration_semantic"])
    duration_seconds = (
        aggregate_base + elapsed
        if semantic == "aggregate_live"
        else elapsed
    )
    return {
        "display_span_id": str(live_clock["display_span_id"]),
        "activity_id": activity_id,
        "anchor_activity_id": activity_id,
        "source": source_for_state(display_live_state),
        "start_time": str(snapshot.get("start_time") or "") if snapshot else "",
        "end_time": "",
        "duration": format_duration(duration_seconds),
        "duration_seconds": duration_seconds,
        "live_clock": dict(live_clock),
        "project_id": int(project_fields["project_id"]),
        "project_name": project_fields["project_name"],
        "project_description": project_fields["project_description"],
        "resource_name": _display_resource_name(snapshot) if snapshot else "",
        "resource_identity_hash": _resource_identity_hash(snapshot),
        "is_current": True,
        "is_virtual": False,
        "is_persisted": is_persisted,
        "is_visible_in_current": True,
        "is_visible_in_recent": bool(policy.materialize_recent),
        "is_visible_in_timeline": bool(policy.materialize_timeline),
        "is_visible_in_details": bool(policy.materialize_details),
        "editable": False,
        "exportable": False,
        "edit_disabled": True,
        "disable_reason": LIVE_EDIT_DISABLE_REASON,
        "display_project": project_fields["display_project"],
        "is_uncategorized": bool(project_fields["is_uncategorized"]),
        "is_classified": bool(project_fields["is_classified"]),
    }


def _signature_project_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "id": value.get("id"),
        "name": str(value.get("name") or ""),
        "source": str(value.get("source") or ""),
    }


def _resource_identity_hash(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return ""
    for field in (
        "resource_identity_key",
        "activity_identity_key",
        "resource_display_name",
        "activity_display_name",
        "app_name",
        "process_name",
    ):
        value = str(snapshot.get(field) or "").strip().lower()
        if value:
            return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return ""
