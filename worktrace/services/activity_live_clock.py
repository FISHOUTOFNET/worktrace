from __future__ import annotations

import hashlib
import time

from ..contracts.live_display_contracts import (
    ActivitySnapshotContract,
    CurrentActivityContract,
    LiveClockContract,
)
from .activity_display_policy import DisplaySessionPolicy
from .live_display_service import _stable_live_key_hash
from .live_time_service import snapshot_elapsed_seconds, snapshot_start_time

CURRENT_LIVE = "current_live"
AGGREGATE_LIVE = "aggregate_live"
STATIC_CLOSED = "static_closed"


def build_suppressed_live_clock() -> LiveClockContract:
    return {
        "sampled_at_epoch_ms": int(time.time() * 1000),
        "started_at_epoch_ms": 0,
        "elapsed_seconds_at_sample": 0,
        "aggregate_base_seconds": 0,
        "duration_semantic": STATIC_CLOSED,
        "is_live": False,
        "live_state": "none",
        "display_span_id": "",
        "stable_live_key_hash": "",
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
    del anchor, summary, report_date, today
    stable_hash = _stable_live_key_hash(snapshot)
    display_span_id = ("span:" + stable_hash) if stable_hash else ""
    elapsed = int(snapshot_elapsed_seconds(snapshot))
    start_dt = snapshot_start_time(snapshot)
    started_at = int(start_dt.timestamp() * 1000) if start_dt is not None else 0
    sampled_at = (
        started_at + elapsed * 1000
        if started_at > 0
        else int(time.time() * 1000)
    )
    state = (
        "persisted_open"
        if display_live_state == "persisted_open"
        else "suppressed"
        if snapshot is not None
        else "none"
    )
    project_live = bool(
        state == "persisted_open" and policy.project_duration_live and started_at > 0
    )
    current_live = bool(
        state == "persisted_open" and policy.current_duration_live and started_at > 0
    )
    if project_live:
        semantic = AGGREGATE_LIVE
        aggregate_base = int(policy.aggregate_base_seconds)
    elif current_live:
        semantic = CURRENT_LIVE
        aggregate_base = 0
    else:
        semantic = STATIC_CLOSED
        aggregate_base = 0
    return {
        "sampled_at_epoch_ms": int(sampled_at),
        "started_at_epoch_ms": int(started_at),
        "elapsed_seconds_at_sample": int(elapsed),
        "aggregate_base_seconds": int(aggregate_base),
        "duration_semantic": semantic,
        "is_live": bool(project_live or current_live),
        "live_state": state,
        "display_span_id": display_span_id,
        "stable_live_key_hash": stable_hash,
    }
