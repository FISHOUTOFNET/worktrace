"""Lightweight refresh-state ViewModel owner.

This path deliberately avoids canonical report projection construction. It
samples runtime activity once and exposes only the static metadata and exact
LiveClock inputs required by the canonical runtime-envelope owner.
"""
from __future__ import annotations

from typing import Any

from . import page_revision_service, timeline_service
from .activity_display_model_service import build_activity_display_model
from .report_projection_identity import stable_json_hash
from .report_revision_service import get_report_structure_revision
from .runtime_activity_state_service import get_runtime_activity_snapshot


def get_refresh_state_view_model(
    report_date: str | None = None,
) -> dict[str, Any]:
    snapshot = get_runtime_activity_snapshot()
    today = timeline_service.get_default_report_date()
    scoped_date = report_date or today
    model = build_activity_display_model(
        report_date=today,
        today=today,
        snapshot=snapshot,
    )
    live_clock = dict(model.get("live_clock") or {})
    current_activity = dict(model.get("current_activity") or {})
    live_revision = page_revision_service.live_revision(current_activity, live_clock)
    structure_revision = get_report_structure_revision(scoped_date)
    page_revision = stable_json_hash(
        [structure_revision, live_revision if scoped_date == today else ""]
    )
    return {
        "ok": True,
        "today": today,
        "report_date": scoped_date,
        "current_activity": current_activity,
        "live_clock": live_clock,
        "sample_id": str(model.get("sample_id") or ""),
        "live_revision": live_revision,
        "structure_revision": structure_revision,
        "page_revision": page_revision,
    }


__all__ = ["get_refresh_state_view_model"]
