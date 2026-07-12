"""Timeline, activity, and live-time facade for the UI.

Wraps ``timeline_service``, the activity-editing helpers from
the project-selection helper from ``project_service``,
and the pure live-time helpers from ``live_time_service``.
"""

from __future__ import annotations

from typing import Any

from ..services import report_session_operation_service, timeline_service
from ..services.activity_edit_policy import project_editability_code
from ..services.live_time_service import (
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
)

NOT_PROJECT_ACTIVITY_CODE = "not_project_activity"



def get_default_report_date() -> str:
    return timeline_service.get_default_report_date()


def get_project_sessions_by_date(
    date: str,
) -> list[dict[str, Any]]:
    return timeline_service.get_project_sessions_by_date(date)


def get_project_sessions_by_range(
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    return timeline_service.get_project_sessions_by_range(start_date, end_date)



# Maximum length for a session note. Session overrides have no length
# constraint, so the API enforces a reasonable upper bound to
# keep the WebView editing surface bounded and testable.
TIMELINE_NOTE_MAX_LENGTH = 2000

# Maximum allowed value for ``adjusted_duration_seconds``. A single day has
# 86400 seconds; allowing up to that keeps the override sane without
# rejecting long but legitimate sessions.
TIMELINE_ADJUSTED_DURATION_MAX_SECONDS = 24 * 60 * 60


def save_timeline_session_edit(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> dict[str, Any]:
    date = _validate_report_date(report_date)
    key = _validate_projection_instance_key(projection_instance_key)
    revision = _validate_projection_revision(expected_projection_revision)
    pid = _validate_optional_project_id(project_id)
    duration = _validate_adjusted_duration(adjusted_duration_seconds)
    text = _validate_note(note)
    result = report_session_operation_service.edit_session(
        date,
        key,
        revision,
        _validate_request_id(request_id),
        project_id=pid,
        adjusted_duration_seconds=duration,
        note=text,
    )
    return _operation_result(result)


def hide_timeline_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> dict[str, Any]:
    date = _validate_report_date(report_date)
    key = _validate_projection_instance_key(projection_instance_key)
    result = report_session_operation_service.hide_session(date, key, _validate_projection_revision(expected_projection_revision), _validate_request_id(request_id))
    return _operation_result(result)


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
    date = _validate_report_date(report_date)
    key = _validate_projection_instance_key(projection_instance_key)
    target_key = _validate_projection_instance_key(target_projection_instance_key)
    result = report_session_operation_service.merge_session(
        date,
        key,
        direction,
        _validate_request_id(request_id),
        expected_projection_revision=_validate_projection_revision(expected_projection_revision),
        target_projection_instance_key=target_key,
        target_expected_projection_revision=_validate_projection_revision(target_expected_projection_revision),
    )
    return _operation_result(result)


def split_timeline_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> dict[str, Any]:
    date = _validate_report_date(report_date)
    key = _validate_projection_instance_key(projection_instance_key)
    result = report_session_operation_service.split_session(date, key, _validate_projection_revision(expected_projection_revision), _validate_request_id(request_id))
    return _operation_result(result)


def copy_timeline_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> dict[str, Any]:
    date = _validate_report_date(report_date)
    key = _validate_projection_instance_key(projection_instance_key)
    result = report_session_operation_service.copy_session(date, key, _validate_projection_revision(expected_projection_revision), _validate_request_id(request_id))
    return _operation_result(result)


def hide_timeline_session_activity(
    report_date: str,
    projection_instance_key: str,
    summary_id: str,
    expected_projection_revision: str,
    request_id: str,
) -> dict[str, Any]:
    if not isinstance(summary_id, str) or not summary_id.strip():
        raise ValueError("invalid_session_identity")
    date = _validate_report_date(report_date)
    key = _validate_projection_instance_key(projection_instance_key)
    result = report_session_operation_service.hide_session_activity(
        date,
        key,
        summary_id.strip(),
        _validate_projection_revision(expected_projection_revision),
        _validate_request_id(request_id),
    )
    return _operation_result(result)


def _validate_project_id(project_id: int) -> int:
    # ``bool`` is a subclass of ``int`` in Python, so ``True`` would otherwise
    # coerce to ``1``. Reject it explicitly to avoid surprising writes.
    if isinstance(project_id, bool):
        raise ValueError("project_id must be an integer")
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        raise ValueError("project_id must be an integer")
    if pid <= 0:
        raise ValueError("project_id must be a positive integer")
    return pid


def _validate_optional_project_id(project_id: int | None) -> int | None:
    if project_id is None:
        return None
    return _validate_project_id(project_id)


def _validate_report_date(report_date: str) -> str:
    from datetime import date as date_type

    if not isinstance(report_date, str) or not report_date:
        raise ValueError("report_date must be a YYYY-MM-DD string")
    try:
        date_type.fromisoformat(report_date)
    except ValueError:
        raise ValueError("report_date must be a YYYY-MM-DD string")
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
    except ValueError:
        raise ValueError("invalid_session_identity")
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
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:."
    if any(ch not in allowed for ch in text):
        raise ValueError("invalid_request_id")
    return text


def _operation_result(result) -> dict[str, Any]:
    return {
        "ok": True,
        "request_id": result.request_id,
        "outcome_type": result.outcome_type,
        "operation_id": result.operation_id,
        "report_date": result.report_date,
        "selection_hint": result.selection_hint,
        "snapshot_revision": result.snapshot_revision,
    }


def _validate_note(note: str) -> str:
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    if len(note) > TIMELINE_NOTE_MAX_LENGTH:
        raise ValueError("note exceeds maximum length")
    return "" if not note.strip() else note


def _validate_adjusted_duration(adjusted_duration_seconds: int | None) -> int | None:
    """Validate ``adjusted_duration_seconds``.

    Semantics:
    - ``None`` = no override / clear override.
    - ``0`` = valid explicit override to zero display/declared duration.
    - positive int = valid override.
    - negative = invalid.

    Returns ``None`` when no override is requested. Returns a non-negative
    ``int`` when a valid override is provided (``0`` is allowed).

    Raises ``ValueError``:
    - ``bool`` is rejected (``isinstance(True, int)`` is ``True`` in Python).
    - Negative values are rejected.
    - Non-integer values are rejected.
    - Values exceeding ``TIMELINE_ADJUSTED_DURATION_MAX_SECONDS`` are rejected.
    """
    if adjusted_duration_seconds is None:
        return None
    if isinstance(adjusted_duration_seconds, bool):
        raise ValueError("adjusted_duration_seconds must be an integer")
    try:
        value = int(adjusted_duration_seconds)
    except (TypeError, ValueError):
        raise ValueError("adjusted_duration_seconds must be an integer")
    if value < 0:
        raise ValueError("adjusted_duration_seconds must be a non-negative integer")
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



def get_snapshot_elapsed_seconds(snapshot: dict[str, Any] | None) -> int:
    return snapshot_elapsed_seconds(snapshot)


def get_snapshot_extra_seconds(snapshot: dict[str, Any] | None) -> int:
    return snapshot_extra_seconds(snapshot)


def get_snapshot_persisted_id(snapshot: dict[str, Any] | None) -> int | None:
    return snapshot_persisted_id(snapshot)


def get_snapshot_seconds_for_date_range(
    snapshot: dict[str, Any] | None,
    start_date: str,
    end_date: str,
) -> int:
    return snapshot_seconds_for_date_range(snapshot, start_date, end_date)


__all__ = [
    "TIMELINE_ADJUSTED_DURATION_MAX_SECONDS",
    "TIMELINE_NOTE_MAX_LENGTH",
    "get_default_report_date",
    "get_project_sessions_by_date",
    "get_project_sessions_by_range",
    "get_snapshot_elapsed_seconds",
    "get_snapshot_extra_seconds",
    "get_snapshot_persisted_id",
    "get_snapshot_seconds_for_date_range",
    "hide_timeline_session",
    "hide_timeline_session_activity",
    "list_selectable_projects",
    "copy_timeline_session",
    "merge_timeline_session",
    "save_timeline_session_edit",
    "split_timeline_session",
]
