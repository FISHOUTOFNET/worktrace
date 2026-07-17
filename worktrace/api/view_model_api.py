"""ViewModel API facade — sole bridge-facing page payload boundary."""

from __future__ import annotations

from typing import Any

from ..services import refresh_state_view_model_service, timeline_service, view_model_service
from ..services.live_display_service import build_current_activity_summary
from ..services.live_runtime_envelope_service import attach_live_runtime_envelope
from ..services.page_read_context import page_read_scope


def _attach_runtime(
    payload: dict[str, Any],
    *,
    surface: str,
    scope_report_date: str | None = None,
) -> dict[str, Any]:
    live_report_date = str(
        payload.get("today") or timeline_service.get_default_report_date()
    )
    return attach_live_runtime_envelope(
        payload,
        surface=surface,
        scope_report_date=scope_report_date,
        live_report_date=live_report_date,
    )


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    with page_read_scope():
        payload = view_model_service.get_overview_view_model(today)
        return _attach_runtime(
            payload,
            surface="overview",
            scope_report_date=str(payload.get("date") or today or ""),
        )


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    with page_read_scope():
        payload = view_model_service.get_timeline_view_model(report_date)
        return _attach_runtime(
            payload,
            surface="timeline",
            scope_report_date=str(payload.get("date") or report_date or ""),
        )


def get_session_activity_summary_view_model(
    *,
    report_date: str | None = None,
    projection_instance_key: str,
    expected_projection_revision: str | None = None,
) -> dict[str, Any]:
    with page_read_scope():
        payload = view_model_service.get_session_activity_summary_view_model(
            report_date=report_date,
            projection_instance_key=projection_instance_key,
            expected_projection_revision=expected_projection_revision,
        )
        return _attach_runtime(
            payload,
            surface="details",
            scope_report_date=str(payload.get("date") or report_date or ""),
        )


def get_refresh_state_view_model(report_date: str | None = None) -> dict[str, Any]:
    with page_read_scope():
        payload = refresh_state_view_model_service.get_refresh_state_view_model(
            report_date
        )
        return _attach_runtime(
            payload,
            surface="refresh",
            scope_report_date=str(
                payload.get("report_date") or report_date or ""
            ),
        )


__all__ = [
    "build_current_activity_summary",
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
