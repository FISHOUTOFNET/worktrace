"""ViewModel API facade — sole bridge-facing entry for page display payloads."""

from __future__ import annotations

from typing import Any

from ..services.live_display_service import build_current_activity_summary
from ..services.page_revision_service import apply_page_revision
from ..services.report_projection_snapshot_service import snapshot_read_scope
from ..services import view_model_hardening_service


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    with snapshot_read_scope():
        payload = view_model_hardening_service.get_overview_view_model(today)
    report_date = str(payload.get("date") or today or "")
    return apply_page_revision(
        payload,
        report_date=report_date,
        today=report_date,
    )


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    with snapshot_read_scope():
        payload = view_model_hardening_service.get_timeline_view_model(report_date)
    from ..services.timeline_service import get_default_report_date

    return apply_page_revision(
        payload,
        report_date=str(payload.get("date") or report_date or ""),
        today=get_default_report_date(),
    )


def get_session_activity_summary_view_model(
    *,
    report_date: str | None = None,
    projection_instance_key: str,
    expected_projection_revision: str | None = None,
) -> dict[str, Any]:
    with snapshot_read_scope():
        payload = view_model_hardening_service.get_session_activity_summary_view_model(
            report_date=report_date,
            projection_instance_key=projection_instance_key,
            expected_projection_revision=expected_projection_revision,
        )
    from ..services.timeline_service import get_default_report_date

    return apply_page_revision(
        payload,
        report_date=str(payload.get("date") or report_date or ""),
        today=get_default_report_date(),
    )


def get_refresh_state_view_model(report_date: str | None = None) -> dict[str, Any]:
    return view_model_hardening_service.get_refresh_state_view_model(report_date)


__all__ = [
    "build_current_activity_summary",
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
