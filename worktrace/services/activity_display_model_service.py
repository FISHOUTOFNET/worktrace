"""Activity Display Model orchestration layer.

This module remains the only service entry point that samples the current
activity snapshot and decides the full live display model. Policy, live clock,
span construction, and row overlay live in focused sibling modules.
"""

from __future__ import annotations

import json
from typing import Any

from ..contracts.live_display_contracts import ActivitySnapshotContract
from . import timeline_service
from .activity_display_policy import (
    build_display_session_policy,
    build_status_display_item,
    classify_display_live_state,
)
from .activity_display_span import (
    build_current_activity_display,
    build_display_span,
    build_display_structural_signature,
)
from .activity_live_clock import build_project_live_clock, build_suppressed_live_clock
from .live_display_service import build_current_activity_summary, classify_live_state
from .settings_service import get_setting

_UNSET = object()


def _get_current_activity_snapshot() -> ActivitySnapshotContract | None:
    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def build_activity_display_model(
    report_date: str | None = None,
    today: str | None = None,
    snapshot: Any = _UNSET,
) -> dict[str, Any]:
    """Build the unified Activity Display Model from a single snapshot."""
    if snapshot is _UNSET:
        snapshot = _get_current_activity_snapshot()
    today = today or timeline_service.get_default_report_date()
    report_date = report_date or today
    is_today = report_date == today

    base_state = classify_live_state(snapshot)
    # Normal live display is exclusively backed by its own persisted open
    # activity. It never borrows or reopens a previously closed anchor.
    anchor: dict[str, Any] | None = None
    if not is_today:
        display_live_state = "none"
    else:
        display_live_state = classify_display_live_state(snapshot, report_date, today)

    summary = build_current_activity_summary(
        snapshot,
        report_date=report_date,
        today=today,
    )
    policy = build_display_session_policy(
        snapshot,
        report_date,
        today or "",
        base_state,
        anchor,
        display_live_state,
        summary,
    )
    if not is_today:
        live_clock = build_suppressed_live_clock()
    else:
        live_clock = build_project_live_clock(
            snapshot,
            display_live_state,
            anchor,
            summary,
            policy,
            report_date,
            today or "",
        )

    display_spans: list[dict[str, Any]] = []
    if is_today and (
        policy.materialize_recent
        or policy.materialize_timeline
        or policy.materialize_details
    ):
        display_spans.append(
            build_display_span(
                snapshot,
                display_live_state,
                anchor,
                live_clock,
                summary,
                report_date,
                today or "",
            )
        )

    current_activity = build_current_activity_display(
        snapshot,
        display_live_state,
        anchor,
        summary,
        live_clock,
    )
    status_display_item = build_status_display_item(
        snapshot,
        display_live_state,
        report_date,
        today or "",
    )
    display_structural_signature = build_display_structural_signature(
        snapshot,
        display_live_state,
        anchor,
        live_clock,
        current_activity,
        report_date,
        today or "",
        is_today,
    )

    return {
        "ok": True,
        "date": report_date,
        "is_today": bool(is_today),
        "sample_id": str(live_clock.get("stable_live_key_hash") or ""),
        "live_clock": live_clock,
        "current_activity": current_activity,
        "status_display_item": status_display_item,
        "display_spans": display_spans,
        "display_structural_signature": display_structural_signature,
        "display_policy": policy.to_dict(),
    }


__all__ = ["build_activity_display_model"]
