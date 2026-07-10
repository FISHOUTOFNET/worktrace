from __future__ import annotations

import hashlib
import json
from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from ..contracts.live_display_contracts import (
    ActivitySnapshotContract,
    CurrentActivityContract,
    DisplaySpanContract,
    LiveClockContract,
)
from ..formatters import format_duration
from .activity_display_policy import anchor_project_fields
from .activity_live_clock import CURRENT_LIVE, current_resource_identity_hash
from .live_display_service import (
    _display_resource_name,
    _snapshot_display_project_fields,
    _stable_live_key,
)
from .live_time_service import snapshot_elapsed_seconds, snapshot_persisted_id

LIVE_EDIT_DISABLE_REASON = "当前活动尚未进入历史，暂不能编辑"


def build_current_activity_display(
    snapshot: ActivitySnapshotContract | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    summary: CurrentActivityContract,
    live_clock: LiveClockContract,
) -> CurrentActivityContract:
    if not snapshot:
        return {
            "active": False,
            "display": "无",
            "elapsed_seconds": 0,
            "resource_elapsed_seconds": 0,
            "is_paused": False,
            "status": "",
            "is_persisted": False,
            "project_name": "",
            "project_id": 0,
            "persisted_activity_id": 0,
            "live_state": "none",
            "is_in_progress": False,
            "is_virtual_live": False,
            "live_display_key": "",
            "stable_live_key": "",
            "stable_live_key_hash": "",
            "live_started_at_epoch_ms": 0,
            "carry_seconds": 0,
            "resource_name": "",
            "app_name": "",
            "start_time": "",
            "end_time": None,
            "activity_id": None,
            "source": "none",
            "is_uncategorized": True,
            "is_classified": False,
            "project_description": "",
            "display_project": None,
            "candidate_project": None,
            "project_transition": {
                "pending": False,
                "started_at": "",
                "elapsed_seconds": 0,
                "threshold_seconds": 30,
                "from_project_id": None,
                "to_project_id": None,
            },
            "project_transition_pending": False,
            "display_span_id": "",
            "live_clock": live_clock,
            "current_activity_display_span_id": "",
            "current_resource_identity_hash": "",
            "current_duration_live": False,
            "is_live": False,
            "project_duration_live": False,
            "display_base_seconds": 0,
            "live_base_seconds": 0,
            "duration_semantic": CURRENT_LIVE,
            "current_live_seconds_at_sample": 0,
            "current_live_base_seconds": 0,
            "duration_seconds_at_sample": 0,
            "aggregate_duration_seconds_at_sample": 0,
            "aggregate_display_base_seconds": 0,
            "display_session_kind": "none",
            "base_policy": "suppressed",
            "status_only_reason": "",
            "base_policy_reason": "no_snapshot",
        }

    display = dict(summary)
    display["live_clock"] = live_clock
    display["display_span_id"] = live_clock.get("display_span_id") or ""
    display["stable_live_key_hash"] = (
        live_clock.get("stable_live_key_hash")
        or display.get("stable_live_key_hash")
        or ""
    )
    identity_hash = current_resource_identity_hash(snapshot)
    display["current_activity_display_span_id"] = (
        "current:" + identity_hash
    ) if identity_hash else ""
    display["current_resource_identity_hash"] = identity_hash
    display["live_state"] = display_live_state
    display["live_started_at_epoch_ms"] = int(
        live_clock.get("live_started_at_epoch_ms") or 0
    )
    display["carry_seconds"] = int(live_clock.get("carry_seconds") or 0)
    display["current_duration_live"] = bool(live_clock.get("current_duration_live"))
    display["is_live"] = bool(live_clock.get("is_live"))
    display["project_duration_live"] = bool(
        live_clock.get("project_duration_live", live_clock.get("is_project_duration_live"))
    )
    display["display_base_seconds"] = 0
    display["live_base_seconds"] = 0
    display["duration_semantic"] = CURRENT_LIVE
    current_elapsed = int(snapshot_elapsed_seconds(snapshot))
    display["resource_elapsed_seconds"] = current_elapsed
    display["elapsed_seconds"] = current_elapsed
    display["duration_seconds_at_sample"] = display["elapsed_seconds"]
    display["current_live_seconds_at_sample"] = int(
        live_clock.get("current_live_seconds_at_sample")
        or live_clock.get("current_elapsed_at_sample")
        or current_elapsed
    )
    display["current_live_base_seconds"] = 0
    display["aggregate_duration_seconds_at_sample"] = int(
        live_clock.get("aggregate_duration_seconds_at_sample")
        or current_elapsed
    )
    display["aggregate_display_base_seconds"] = int(
        live_clock.get("aggregate_display_base_seconds")
        or live_clock.get("display_base_seconds")
        or 0
    )
    display["display_session_kind"] = str(live_clock.get("display_session_kind") or "")
    display["base_policy"] = str(live_clock.get("base_policy") or "")
    display["status_only_reason"] = str(live_clock.get("status_only_reason") or "")
    display["base_policy_reason"] = str(live_clock.get("base_policy_reason") or "")
    display["is_virtual_live"] = display_live_state in (
        "borrowed_anchor_pending",
        "current_only_pending",
    )
    display["is_in_progress"] = display_live_state == "persisted_open"
    display["source"] = source_for_state(display_live_state)
    return display


def build_display_structural_signature(
    snapshot: ActivitySnapshotContract | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    live_clock: LiveClockContract,
    current_activity: CurrentActivityContract,
    report_date: str,
    today: str,
    is_today: bool,
) -> str:
    project_transition = current_activity.get("project_transition") or {}
    display_policy = live_clock.get("display_policy") or {}
    signature_payload = {
        "current_activity_stable_key": str(
            current_activity.get("stable_live_key") or _stable_live_key(snapshot)
        ),
        "display_live_state": display_live_state,
        "is_persisted": bool(snapshot and snapshot.get("is_persisted")),
        "persisted_activity_id": int(snapshot_persisted_id(snapshot) or 0)
        if snapshot
        else 0,
        "display_project": _signature_project_dict(current_activity.get("display_project")),
        "candidate_project": _signature_project_dict(current_activity.get("candidate_project")),
        "project_transition": {
            "pending": bool(project_transition.get("pending")),
            "from_project_id": project_transition.get("from_project_id"),
            "to_project_id": project_transition.get("to_project_id"),
        },
        "project_live_span": {
            "display_span_id": str(live_clock.get("display_span_id") or ""),
            "anchor_activity_id": int(anchor.get("id") or 0) if anchor else 0,
            "anchor_project_id": int(display_policy.get("borrowed_anchor_project_id") or 0),
            "anchor_project_name": str(
                display_policy.get("borrowed_anchor_project_name") or ""
            ),
            "materialize_recent": bool(display_policy.get("materialize_recent")),
            "materialize_timeline": bool(display_policy.get("materialize_timeline")),
            "materialize_details": bool(display_policy.get("materialize_details")),
        },
        "base_policy": {
            "display_session_kind": str(live_clock.get("display_session_kind") or ""),
            "base_policy": str(live_clock.get("base_policy") or ""),
            "status_only_reason": str(live_clock.get("status_only_reason") or ""),
            "base_policy_reason": str(live_clock.get("base_policy_reason") or ""),
        },
        "current_activity_display_span_id": str(
            current_activity.get("current_activity_display_span_id") or ""
        ),
        "report_date": report_date,
        "today": today,
        "is_today": bool(is_today),
    }
    return json.dumps(signature_payload, sort_keys=True, ensure_ascii=False)


def source_for_state(state: str) -> str:
    if state == "persisted_open":
        return "db"
    if state in ("borrowed_anchor_pending", "current_only_pending"):
        return "snapshot"
    return "none"


def build_display_span(
    snapshot: ActivitySnapshotContract | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    live_clock: LiveClockContract,
    summary: CurrentActivityContract,
    report_date: str,
    today: str,
) -> DisplaySpanContract:
    anchor_id = 0
    activity_id = 0
    start_time = str(snapshot.get("start_time") or "") if snapshot else ""
    project_fields = _snapshot_display_project_fields(snapshot)
    current_live_seconds = int(
        live_clock.get("current_live_seconds_at_sample")
        or live_clock.get("current_elapsed_at_sample")
        or 0
    )
    aggregate_duration = int(
        live_clock.get("aggregate_duration_seconds_at_sample")
        or live_clock.get("duration_seconds_at_sample")
        or current_live_seconds
    )
    aggregate_base = int(
        live_clock.get("aggregate_display_base_seconds")
        or live_clock.get("display_base_seconds")
        or 0
    )
    policy = live_clock.get("display_policy") or {}
    live_anchor_base_seconds = 0

    if display_live_state == "persisted_open":
        activity_id = int(snapshot_persisted_id(snapshot) or 0) if snapshot else 0
        anchor_id = activity_id
        source = "db"
        is_virtual = False
        is_persisted = True
        is_absorbed = False
        project_name = project_fields["project_name"]
        project_description = project_fields["project_description"]
        project_id = project_fields["project_id"]
        display_project = project_fields["display_project"]
        candidate_project = project_fields["candidate_project"]
        is_uncategorized = bool(project_fields["is_uncategorized"])
        is_classified = bool(project_fields["is_classified"])
    elif display_live_state == "borrowed_anchor_pending" and anchor:
        anchor_id = int(anchor.get("id") or 0)
        activity_id = anchor_id
        start_time = str(anchor.get("start_time") or start_time)
        source = "borrowed_anchor_pending"
        is_virtual = True
        is_persisted = False
        is_absorbed = True
        live_anchor_base_seconds = int(anchor.get("duration_seconds") or 0)
        anchor_project = anchor_project_fields(anchor)
        project_name = str(anchor_project["project_name"] or UNCATEGORIZED_PROJECT)
        project_description = str(anchor_project["project_description"] or "")
        project_id = int(anchor_project["project_id"] or 0)
        display_project = anchor_project["display_project"]
        candidate_project = anchor_project["candidate_project"]
        is_uncategorized = bool(anchor_project["is_uncategorized"])
        is_classified = bool(anchor_project["is_classified"])
    else:
        source = "snapshot"
        is_virtual = True
        is_persisted = False
        is_absorbed = False
        project_name = project_fields["project_name"]
        project_description = project_fields["project_description"]
        project_id = project_fields["project_id"]
        display_project = project_fields["display_project"]
        candidate_project = project_fields["candidate_project"]
        is_uncategorized = bool(project_fields["is_uncategorized"])
        is_classified = bool(project_fields["is_classified"])

    return {
        "display_span_id": live_clock.get("display_span_id") or "",
        "activity_id": int(activity_id),
        "anchor_activity_id": int(anchor_id),
        "source": source,
        "live_state": display_live_state,
        "start_time": start_time,
        "end_time": "",
        "duration_semantic": "",
        "duration": format_duration(aggregate_duration),
        "duration_seconds": aggregate_duration,
        "duration_seconds_at_sample": aggregate_duration,
        "current_live_seconds_at_sample": current_live_seconds,
        "current_live_base_seconds": 0,
        "aggregate_duration_seconds_at_sample": aggregate_duration,
        "aggregate_display_base_seconds": aggregate_base,
        "display_base_seconds": aggregate_base,
        "live_clock": live_clock,
        "project_id": int(project_id),
        "project_name": project_name,
        "project_description": project_description,
        "resource_name": _display_resource_name(snapshot) if snapshot else "",
        # The raw resource identity is privacy-sensitive.  Overlay only needs
        # equality, so expose a deterministic digest rather than the key.
        "resource_identity_hash": _resource_identity_hash(snapshot),
        "is_current": True,
        "is_live": bool(live_clock.get("is_live")),
        "project_duration_live": bool(
            live_clock.get("project_duration_live", live_clock.get("is_project_duration_live"))
        ),
        "current_duration_live": bool(live_clock.get("current_duration_live")),
        "display_session_kind": str(live_clock.get("display_session_kind") or ""),
        "base_policy": str(live_clock.get("base_policy") or ""),
        "status_only_reason": str(live_clock.get("status_only_reason") or ""),
        "base_policy_reason": str(live_clock.get("base_policy_reason") or ""),
        "is_virtual": bool(is_virtual),
        "is_persisted": bool(is_persisted),
        "is_visible_in_current": True,
        "is_visible_in_recent": bool(policy.get("materialize_recent")),
        "is_visible_in_timeline": bool(policy.get("materialize_timeline")),
        "is_visible_in_details": bool(policy.get("materialize_details")),
        "is_absorbed": bool(is_absorbed),
        "is_display_only": display_live_state == "borrowed_anchor_pending",
        "display_only": display_live_state == "borrowed_anchor_pending",
        "editable": False,
        "exportable": False,
        "edit_disabled": True,
        "disable_reason": LIVE_EDIT_DISABLE_REASON,
        "display_project": display_project,
        "candidate_project": candidate_project,
        "project_transition": project_fields["project_transition"],
        "project_transition_pending": bool(project_fields["project_transition_pending"]),
        "live_anchor_activity_id": int(anchor_id),
        "live_anchor_base_seconds": int(live_anchor_base_seconds),
        "is_uncategorized": bool(is_uncategorized),
        "is_classified": bool(is_classified),
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
