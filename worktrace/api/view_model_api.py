"""ViewModel API facade — sole bridge-facing page payload boundary."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from ..services import refresh_state_view_model_service, timeline_service, view_model_service
from ..services.live_display_service import build_current_activity_summary
from ..services.live_runtime_envelope_service import attach_live_runtime_envelope
from ..services.page_read_context import page_read_scope

if TYPE_CHECKING:
    from ..runtime.app_runtime import AppRuntime


def _attach_runtime(
    payload: dict[str, Any],
    *,
    surface: str,
    runtime: "AppRuntime | None",
    collector_status: Mapping[str, Any] | None,
    scope_report_date: str | None = None,
) -> dict[str, Any]:
    if runtime is None:
        raise ValueError("runtime_missing")
    if not isinstance(collector_status, Mapping) or not collector_status:
        raise ValueError("collector_status_missing")
    live_report_date = str(
        payload.get("today") or timeline_service.get_default_report_date()
    )
    return attach_live_runtime_envelope(
        payload,
        surface=surface,
        runtime=runtime,
        collector_status=collector_status,
        scope_report_date=scope_report_date,
        live_report_date=live_report_date,
    )


def get_overview_view_model(
    today: str | None = None,
    *,
    runtime: "AppRuntime | None" = None,
    collector_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    with page_read_scope():
        payload = view_model_service.get_overview_view_model(today)
        return _attach_runtime(
            payload,
            surface="overview",
            runtime=runtime,
            collector_status=collector_status,
            scope_report_date=str(payload.get("date") or today or ""),
        )


def get_timeline_view_model(
    report_date: str | None = None,
    *,
    runtime: "AppRuntime | None" = None,
    collector_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    with page_read_scope():
        payload = view_model_service.get_timeline_view_model(report_date)
        return _attach_runtime(
            payload,
            surface="timeline",
            runtime=runtime,
            collector_status=collector_status,
            scope_report_date=str(payload.get("date") or report_date or ""),
        )


def get_session_activity_summary_view_model(
    *,
    report_date: str | None = None,
    projection_instance_key: str,
    expected_projection_revision: str | None = None,
    runtime: "AppRuntime | None" = None,
    collector_status: Mapping[str, Any] | None = None,
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
            runtime=runtime,
            collector_status=collector_status,
            scope_report_date=str(payload.get("date") or report_date or ""),
        )


def get_refresh_state_view_model(
    report_date: str | None = None,
    *,
    runtime: "AppRuntime | None" = None,
    collector_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    with page_read_scope():
        payload = refresh_state_view_model_service.get_refresh_state_view_model(
            report_date
        )
        return _attach_runtime(
            payload,
            surface="refresh",
            runtime=runtime,
            collector_status=collector_status,
            scope_report_date=str(payload.get("report_date") or report_date or ""),
        )


__all__ = [
    "build_current_activity_summary",
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
