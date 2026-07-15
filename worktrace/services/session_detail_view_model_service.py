"""Timeline session-detail ViewModel owner."""

from __future__ import annotations

from typing import Any

from . import timeline_service, view_model_service
from .page_view_model_common import apply_structure_revision


def get_session_activity_summary_view_model(
    *,
    report_date: str | None = None,
    projection_instance_key: str,
    expected_projection_revision: str | None = None,
) -> dict[str, Any]:
    payload = view_model_service.get_session_activity_summary_view_model(
        report_date=report_date,
        projection_instance_key=projection_instance_key,
        expected_projection_revision=expected_projection_revision,
    )
    scoped_date = str(payload.get("date") or report_date or "")
    today = timeline_service.get_default_report_date()
    apply_structure_revision(payload, report_date=scoped_date, today=today)
    return payload


__all__ = ["get_session_activity_summary_view_model"]
