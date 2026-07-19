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
    """Build the exact non-ticking v2 contract used when no span is verified."""

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
    """Build the verified current-span clock used as the row-overlay source.

    Aggregate rows receive their own ``aggregate_live`` clock in
    ``activity_row_overlay``. This source clock therefore always represents the
    current activity itself and never reconstructs time from another DTO field.
    """

    del anchor, summary
    sampled_at = int(time.time() * 1000)
    historical = bool(report_date and today and report_date != today)
    persisted = bool(
        snapshot
        and snapshot.get("is_persisted")
        and int(snapshot.get("persisted_activity_id") or 0) > 0
    )
    live = bool(
        not historical
        and persisted
        and display_live_state == "persisted_open"
        and policy.current_duration_live
    )
    if not live:
        return {
            "sampled_at_epoch_ms": sampled_at,
            "started_at_epoch_ms": 0,
            "elapsed_seconds_at_sample": 0,
            "aggregate_base_seconds": 0,
            "duration_semantic": STATIC_CLOSED,
            "is_live": False,
            "live_state": "suppressed" if snapshot is not None else "none",
            "display_span_id": "",
            "stable_live_key_hash": "",
        }

    stable_hash = _stable_live_key_hash(snapshot)
    start_dt = snapshot_start_time(snapshot)
    started_at = int(start_dt.timestamp() * 1000) if start_dt is not None else 0
    elapsed = int(snapshot_elapsed_seconds(snapshot))
    if started_at <= 0 or elapsed < 0 or not stable_hash:
        return {
            "sampled_at_epoch_ms": sampled_at,
            "started_at_epoch_ms": 0,
            "elapsed_seconds_at_sample": 0,
            "aggregate_base_seconds": 0,
            "duration_semantic": STATIC_CLOSED,
            "is_live": False,
            "live_state": "suppressed",
            "display_span_id": "",
            "stable_live_key_hash": "",
        }

    return {
        "sampled_at_epoch_ms": sampled_at,
        "started_at_epoch_ms": started_at,
        "elapsed_seconds_at_sample": elapsed,
        "aggregate_base_seconds": 0,
        "duration_semantic": CURRENT_LIVE,
        "is_live": True,
        "live_state": "persisted_open",
        "display_span_id": "span:" + stable_hash,
        "stable_live_key_hash": stable_hash,
    }
