"""ViewModel API facade — sole bridge-facing page payload boundary."""

from __future__ import annotations

from typing import Any

from ..services.live_display_service import build_current_activity_summary
from ..services.overview_view_model_service import get_overview_view_model as _overview
from ..services.refresh_state_view_model_service import (
    get_refresh_state_view_model as _refresh_state,
)
from ..services.report_projection_snapshot_service import snapshot_read_scope
from ..services.session_detail_view_model_service import (
    get_session_activity_summary_view_model as _session_detail,
)
from ..services.timeline_view_model_service import get_timeline_view_model as _timeline


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    with snapshot_read_scope():
        return _overview(today)


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    with snapshot_read_scope():
        return _timeline(report_date)


def get_session_activity_summary_view_model(
    *,
    report_date: str | None = None,
    projection_instance_key: str,
    expected_projection_revision: str | None = None,
) -> dict[str, Any]:
    with snapshot_read_scope():
        return _session_detail(
            report_date=report_date,
            projection_instance_key=projection_instance_key,
            expected_projection_revision=expected_projection_revision,
        )


def get_refresh_state_view_model(report_date: str | None = None) -> dict[str, Any]:
    return _refresh_state(report_date)


__all__ = [
    "build_current_activity_summary",
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
