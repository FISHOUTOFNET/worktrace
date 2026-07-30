"""Timeline, activity, and live-time facade for the UI."""

from __future__ import annotations

from typing import Any

from ..domain_limits import ADJUSTED_DURATION_MAX_SECONDS, NOTE_MAX_LENGTH
from ..services import (
    project_service,
    report_session_operation_service,
    timeline_service,
)
from ..services.activity_edit_policy import project_editability_code

NOT_PROJECT_ACTIVITY_CODE = "not_project_activity"
TIMELINE_NOTE_MAX_LENGTH = NOTE_MAX_LENGTH
TIMELINE_ADJUSTED_DURATION_MAX_SECONDS = ADJUSTED_DURATION_MAX_SECONDS


def get_default_report_date() -> str:
    return timeline_service.get_default_report_date()


def get_project_sessions_by_date(date: str) -> list[dict[str, Any]]:
    return timeline_service.get_project_sessions_by_date(date)


def get_project_sessions_by_range(start_date: str, end_date: str) -> list[dict[str, Any]]:
    return timeline_service.get_project_sessions_by_range(start_date, end_date)


def save_timeline_session_edit(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> dict[str, Any]:
    result = report_session_operation_service.edit_session(
        _validate_report_date(report_date),
        _validate_projection_instance_key(projection_instance_key),
        _validate_projection_revision(expected_projection_revision),
        _validate_request_id(request_id),
        project_id=_validate_optional_project_id(project_id),
        adjusted_duration_seconds=_validate_adjusted_duration(
            adjusted_duration_seconds
        ),
        note=_validate_note(note),
    )
    return _operation_result(result)


def hide_timeline_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
) -> dict[str, Any]:
    return _operation_result(
        report_session_operation_service.hide_session(
            _validate_report_date(report_date),
            _validate_projection_instance_key(projection_instance_key),
            _validate_projection_revision(expected_projection_revision),
            _validate_request_id(request_id),
        )
    )


def merge_timeline_session(
    report_date: str,
    projection_instance_key: str,
    direction: str,
    expected_projection_revision: str,
    request_id: str,
    target_projection_instance_key: str,
    target_expected_projection_revision: str,
) -> dict[str, Any]:
    if direction not in {"previous", "next"}:
        raise ValueError("invalid_direction")
    return _operation_result(
        report_session_operation_service.merge_session(
            _validate_report_date(report_date),
            _validate_projection_instance_key(projection_instance_key),
            direction,
            _validate_request_id(request_id),
            expected_projection_revision=_validate_projection_revision(
                expected_projection_revision
            ),
            target_projection_instance_key=_validate_projection_instance_key(
                target_projection_instance_key
            ),
            target_expected_projection_revision=_validate_projection_revision(
                target_expected_projection_revision
            ),
        )
    )


def split_timeline_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
) -> dict[str, Any]:
    return _operation_result(
        report_session_operation_service.split_session(
            _validate_report_date(report_date),
            _validate_projection_instance_key(projection_instance_key),
            _validate_projection_revision(expected_projection_revision),
            _validate_request_id(request_id),
        )
    )


def copy_timeline_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
) -> dict[str, Any]:
    return _operation_result(
        report_session_operation_service.copy_session(
            _validate_report_date(report_date),
            _validate_projection_instance_key(projection_instance_key),
            _validate_projection_revision(expected_projection_revision),
            _validate_request_id(request_id),
        )
    )


def hide_timeline_session_activity(
    report_date: str,
    projection_instance_key: str,
    summary_id: str,
    expected_projection_revision: str,
    request_id: str,
) -> dict[str, Any]:
    if not isinstance(summary_id, str) or not summary_id.strip():
        raise ValueError("invalid_session_identity")
    return _operation_result(
        report_session_operation_service.hide_session_activity(
            _validate_report_date(report_date),
            _validate_projection_instance_key(projection_instance_key),
            summary_id.strip(),
            _validate_projection_revision(expected_projection_revision),
            _validate_request_id(request_id),
        )
    )


def _validate_project_id(project_id: int) -> int:
    if isinstance(project_id, bool):
        raise ValueError("project_id must be an integer")
    try:
        value = int(project_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("project_id must be an integer") from exc
    if value <= 0:
        raise ValueError("project_id must be a positive integer")
    return value


def _validate_optional_project_id(project_id: int | None) -> int | None:
    return None if project_id is None else _validate_project_id(project_id)


def _validate_report_date(report_date: str) -> str:
    from datetime import date as date_type

    if not isinstance(report_date, str) or not report_date:
        raise ValueError("report_date must be a YYYY-MM-DD string")
    try:
        date_type.fromisoformat(report_date)
    except ValueError as exc:
        raise ValueError("report_date must be a YYYY-MM-DD string") from exc
    return report_date


def _validate_projection_instance_key(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("invalid_session_identity")
    return value.strip()


def _validate_projection_revision(value: str) -> str:
    if not isinstance(value, str) or len(value.strip()) != 40:
        raise ValueError("invalid_session_identity")
    try:
        int(value.strip(), 16)
    except ValueError as exc:
        raise ValueError("invalid_session_identity") from exc
    return value.strip()


def _validate_optional_projection_revision(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    return _validate_projection_revision(value)


def _validate_request_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_request_id")
    text = value.strip()
    if not text or len(text) > 120:
        raise ValueError("invalid_request_id")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:。".replace(
        "。", "."
    )
    if any(character not in allowed for character in text):
        raise ValueError("invalid_request_id")
    return text


def _operation_result(result) -> dict[str, Any]:
    return {
        "ok": True,
        "request_id": result.request_id,
        "outcome_type": result.outcome_type,
        "operation_id": result.operation_id,
        "report_date": result.report_date,
        "selection_hint": dict(result.selection_hint)
        if result.selection_hint is not None
        else None,
        "snapshot_revision": result.snapshot_revision,
    }


def _validate_note(note: str) -> str:
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    if len(note) > TIMELINE_NOTE_MAX_LENGTH:
        raise ValueError("note exceeds maximum length")
    return "" if not note.strip() else note


def _validate_adjusted_duration(
    adjusted_duration_seconds: int | None,
) -> int | None:
    if adjusted_duration_seconds is None:
        return None
    if isinstance(adjusted_duration_seconds, bool):
        raise ValueError("adjusted_duration_seconds must be an integer")
    try:
        value = int(adjusted_duration_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("adjusted_duration_seconds must be an integer") from exc
    if value < 0:
        raise ValueError(
            "adjusted_duration_seconds must be a non-negative integer"
        )
    if value > TIMELINE_ADJUSTED_DURATION_MAX_SECONDS:
        raise ValueError("adjusted_duration_seconds exceeds maximum")
    return value


def _project_editability_code(activity: dict | None) -> str:
    code = project_editability_code(activity)
    if code in {"", "activity_not_project_activity"}:
        return NOT_PROJECT_ACTIVITY_CODE if code else ""
    if code in {"activity_not_found", "activity_deleted"}:
        return "invalid_id"
    if code == "activity_hidden":
        return "hidden_activity"
    if code == "activity_in_progress":
        return "in_progress"
    return NOT_PROJECT_ACTIVITY_CODE


def _ensure_project_editable_for_value_error(activity: dict | None) -> None:
    code = _project_editability_code(activity)
    if code:
        raise ValueError(code)


def list_selectable_projects() -> list[dict[str, Any]]:
    return project_service.list_selectable_projects()


def list_filter_projects() -> list[dict[str, Any]]:
    return project_service.list_filter_projects()


__all__ = [
    "TIMELINE_ADJUSTED_DURATION_MAX_SECONDS",
    "TIMELINE_NOTE_MAX_LENGTH",
    "copy_timeline_session",
    "get_default_report_date",
    "get_project_sessions_by_date",
    "get_project_sessions_by_range",
    "hide_timeline_session",
    "hide_timeline_session_activity",
    "list_filter_projects",
    "list_selectable_projects",
    "merge_timeline_session",
    "save_timeline_session_edit",
    "split_timeline_session",
]
