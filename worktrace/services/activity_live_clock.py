from __future__ import annotations

import hashlib

from ..contracts.live_display_contracts import (
    ActivitySnapshotContract,
    CurrentActivityContract,
    LiveClockContract,
)
from .activity_display_policy import DisplaySessionPolicy
from .live_display_service import _stable_live_key, _stable_live_key_hash
from .live_time_service import snapshot_elapsed_seconds

CURRENT_LIVE = "current_live"
AGGREGATE_LIVE = "aggregate_live"
STATIC_CLOSED = "static_closed"


def build_suppressed_live_clock() -> LiveClockContract:
    return {
        "display_span_id": "",
        "stable_live_key": "",
        "stable_live_key_hash": "",
        "live_state": "none",
        "live_started_at_epoch_ms": 0,
        "carry_seconds": 0,
        "duration_semantic": STATIC_CLOSED,
        "current_live_seconds_at_sample": 0,
        "current_live_base_seconds": 0,
        "aggregate_duration_seconds_at_sample": 0,
        "aggregate_display_base_seconds": 0,
        "display_base_seconds": 0,
        "duration_seconds_at_sample": 0,
        "active_elapsed_at_sample": 0,
        "current_elapsed_at_sample": 0,
        "is_live": False,
        "is_project_duration_live": False,
        "current_duration_live": False,
        "project_duration_live": False,
        "display_session_kind": "suppressed",
        "base_policy": "suppressed",
        "status_only_reason": "historical_date",
        "base_policy_reason": "historical_date",
        "display_policy": DisplaySessionPolicy(
            display_session_kind="suppressed",
            base_policy="suppressed",
            aggregate_base_seconds=0,
            current_base_seconds=0,
            project_duration_live=False,
            current_duration_live=False,
            materialize_recent=False,
            materialize_timeline=False,
            materialize_details=False,
            status_only_reason="historical_date",
            base_policy_reason="historical_date",
        ).to_dict(),
    }


def current_resource_identity_hash(snapshot: ActivitySnapshotContract | None) -> str:
    resource_identity = ""
    if snapshot:
        resource_identity = str(
            snapshot.get("resource_identity_key")
            or snapshot.get("activity_identity_key")
            or snapshot.get("resource_display_name")
            or snapshot.get("activity_display_name")
            or snapshot.get("app_name")
            or snapshot.get("process_name")
            or ""
        )
    if not snapshot:
        return ""
    parts = [
        resource_identity,
        str(snapshot.get("start_time") or ""),
        str(snapshot.get("status") or ""),
    ]
    key = "|".join(parts)
    if not key.strip("|"):
        return ""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def build_project_live_clock(
    snapshot: ActivitySnapshotContract | None,
    display_live_state: str,
    anchor: dict | None,
    summary: CurrentActivityContract,
    policy: DisplaySessionPolicy,
    report_date: str,
    today: str,
) -> LiveClockContract:
    stable_key = _stable_live_key(snapshot)
    stable_hash = _stable_live_key_hash(snapshot)
    display_span_id = ("span:" + stable_hash) if stable_hash else ""
    live_started_at = int(summary.get("live_started_at_epoch_ms") or 0)
    current_elapsed_at_sample = int(snapshot_elapsed_seconds(snapshot))
    display_base_seconds = int(policy.aggregate_base_seconds)
    carry_seconds = int(policy.aggregate_base_seconds)
    duration_at_sample = display_base_seconds + current_elapsed_at_sample
    is_project_duration_live = bool(policy.project_duration_live)
    is_current_duration_live = bool(policy.current_duration_live and live_started_at > 0)

    return {
        "display_span_id": display_span_id,
        "stable_live_key": stable_key,
        "stable_live_key_hash": stable_hash,
        "live_state": display_live_state,
        "live_started_at_epoch_ms": live_started_at,
        "carry_seconds": int(carry_seconds),
        "duration_semantic": AGGREGATE_LIVE if is_project_duration_live else STATIC_CLOSED,
        "current_live_seconds_at_sample": int(current_elapsed_at_sample),
        "current_live_base_seconds": 0,
        "aggregate_duration_seconds_at_sample": int(duration_at_sample),
        "aggregate_display_base_seconds": int(display_base_seconds),
        "display_base_seconds": int(display_base_seconds),
        "duration_seconds_at_sample": int(duration_at_sample),
        "active_elapsed_at_sample": int(current_elapsed_at_sample),
        "current_elapsed_at_sample": int(current_elapsed_at_sample),
        "project_duration_live": bool(is_project_duration_live),
        "current_duration_live": bool(is_current_duration_live),
        "is_live": bool(is_project_duration_live or is_current_duration_live),
        "is_project_duration_live": bool(is_project_duration_live),
        "display_session_kind": policy.display_session_kind,
        "base_policy": policy.base_policy,
        "status_only_reason": policy.status_only_reason,
        "base_policy_reason": policy.base_policy_reason,
        "display_policy": policy.to_dict(),
    }

