"""Timeline edit compatibility facade over the canonical mutation UOW."""

from __future__ import annotations

from . import report_session_operation_service
from .report_projection_model import MutationResult


def edit_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
    *,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> MutationResult:
    return report_session_operation_service.edit_session(
        report_date,
        projection_instance_key,
        expected_projection_revision,
        request_id,
        project_id=project_id,
        adjusted_duration_seconds=adjusted_duration_seconds,
        note=note,
    )


__all__ = ["edit_session"]
