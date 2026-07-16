"""Timeline page ViewModel owner."""

from __future__ import annotations

from typing import Any

from . import timeline_service, view_model_service
from .page_view_model_common import apply_structure_revision, enable_safe_open_edit
from .report_projection_snapshot_service import build_visible_snapshot


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    payload = view_model_service.get_timeline_view_model(report_date)
    for entry in payload.get("entries") or []:
        enable_safe_open_edit(entry)
    scoped_date = str(payload.get("date") or report_date or "")
    today = timeline_service.get_default_report_date()
    snapshot = build_visible_snapshot(scoped_date, scoped_date)
    apply_structure_revision(
        payload,
        report_date=scoped_date,
        today=today,
        snapshot=snapshot,
    )
    return payload


__all__ = ["get_timeline_view_model"]
