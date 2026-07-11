"""Timeline, activity, and live-time facade for the UI.

Wraps ``timeline_service``, the activity-editing helpers from
``activity_service``, the project-selection helper from ``project_service``,
and the pure live-time helpers from ``live_time_service``.
"""

from __future__ import annotations

from typing import Any

from ..services import activity_service, project_service, report_session_operation_service, timeline_service
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
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict[str, Any]]:
    return timeline_service.get_project_sessions_by_date(
        date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )


def get_project_sessions_by_range(
    start_date: str,
    end_date: str,
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict[str, Any]]:
    return timeline_service.get_project_sessions_by_range(
        start_date,
        end_date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )


def get_session_activity_details(
    activity_ids: list[int],
    report_date: str | None = None,
    ensure_context: bool = True,
) -> list[dict[str, Any]]:
    return timeline_service.get_session_activity_details(
        activity_ids,
        report_date=report_date,
        ensure_context=ensure_context,
    )


def get_session_anchor_folders(activity_ids: list[int]) -> list[str]:
    return timeline_service.get_session_anchor_folders(activity_ids)


def preview_session_project_update(
    session_activity_ids: list[int],
    project_id: int,
) -> dict[str, Any]:
    return timeline_service.preview_session_project_update(session_activity_ids, project_id)



# Maximum length for a session note. Session overrides have no length
# constraint, so the API enforces a reasonable upper bound to
# keep the WebView editing surface bounded and testable.
TIMELINE_NOTE_MAX_LENGTH = 2000

# Maximum allowed value for ``adjusted_duration_seconds``. A single day has
# 86400 seconds; allowing up to that keeps the override sane without
# rejecting long but legitimate sessions.
TIMELINE_ADJUSTED_DURATION_MAX_SECONDS = 24 * 60 * 60


def save_timeline_session_override(
    report_date: str,
    activity_ids: list[int],
    activity_member_hash: str,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> None:
    """Validate and save project, display-duration, and note as one override."""
    date = _validate_report_date(report_date)
    ids = _validate_activity_ids(activity_ids)
    member_hash = _validate_activity_member_hash(activity_member_hash)
    pid = _validate_optional_project_id(project_id)
    duration = _validate_adjusted_duration(adjusted_duration_seconds)
    text = _validate_note(note)
    for aid in ids:
        _ensure_project_editable_for_value_error(activity_service.get_activity(aid))
    timeline_service.update_session_override(
        date,
        ids,
        member_hash,
        project_id=pid,
        adjusted_duration_seconds=duration,
        note=text,
    )


def update_timeline_session_note(
    report_date: str,
    activity_ids: list[int],
    activity_member_hash: str,
    note: str,
) -> None:
    """Validate and write a session note override for the Timeline page."""
    date = _validate_report_date(report_date)
    ids = _validate_activity_ids(activity_ids)
    member_hash = _validate_activity_member_hash(activity_member_hash)
    text = _validate_note(str(note or ""))
    for aid in ids:
        _ensure_project_editable_for_value_error(activity_service.get_activity(aid))
    session = timeline_service.get_project_sessions_by_date(date, include_hidden=True, ensure_context=True)
    current = _find_session_by_identity(session, ids, member_hash)
    timeline_service.update_session_override(
        date,
        ids,
        member_hash,
        project_id=current.get("project_id") if current.get("has_project_override") else None,
        adjusted_duration_seconds=current.get("adjusted_duration_seconds"),
        note=text,
    )


def update_timeline_session_note_and_duration(
    report_date: str,
    activity_ids: list[int],
    activity_member_hash: str,
    note: str,
    adjusted_duration_seconds: int | None = None,
) -> None:
    """Validate and write note + user-adjusted duration for a Timeline session."""
    date = _validate_report_date(report_date)
    ids = _validate_activity_ids(activity_ids)
    member_hash = _validate_activity_member_hash(activity_member_hash)
    text = _validate_note(note)
    duration = _validate_adjusted_duration(adjusted_duration_seconds)
    for aid in ids:
        _ensure_project_editable_for_value_error(activity_service.get_activity(aid))
    timeline_service.update_session_note_and_duration(date, ids, member_hash, text, duration)


def hide_timeline_session(report_date: str, projection_instance_key: str) -> None:
    report_session_operation_service.hide_session(_validate_report_date(report_date), _validate_projection_instance_key(projection_instance_key))


def merge_timeline_session(report_date: str, projection_instance_key: str, direction: str) -> None:
    if direction not in {"previous", "next"}:
        raise ValueError("invalid_direction")
    report_session_operation_service.merge_session(_validate_report_date(report_date), _validate_projection_instance_key(projection_instance_key), direction)


def split_timeline_session(report_date: str, projection_instance_key: str) -> None:
    report_session_operation_service.split_session(_validate_report_date(report_date), _validate_projection_instance_key(projection_instance_key))


def copy_timeline_session(report_date: str, projection_instance_key: str) -> None:
    report_session_operation_service.copy_session(_validate_report_date(report_date), _validate_projection_instance_key(projection_instance_key))


def hide_timeline_session_activity(report_date: str, projection_instance_key: str, summary_id: str) -> None:
    if not isinstance(summary_id, str) or not summary_id.strip():
        raise ValueError("invalid_session_identity")
    report_session_operation_service.hide_session_activity(
        _validate_report_date(report_date), _validate_projection_instance_key(projection_instance_key), summary_id.strip()
    )


def _validate_activity_ids(activity_ids: list[int]) -> list[int]:
    # ``bool`` is a subclass of ``int``; reject it so ``True``/``False`` are
    # not silently coerced to ``1``/``0``.
    if isinstance(activity_ids, bool):
        raise ValueError("activity_ids must be a non-empty list")
    if not isinstance(activity_ids, list) or not activity_ids:
        raise ValueError("activity_ids must be a non-empty list")
    ids: list[int] = []
    seen: set[int] = set()
    for raw in activity_ids:
        if isinstance(raw, bool):
            raise ValueError("activity_ids must contain integers only")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError("activity_ids must contain integers only")
        if value <= 0:
            raise ValueError("activity_ids must contain positive integers")
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    if not ids:
        raise ValueError("activity_ids must be a non-empty list")
    # Verify every id references an existing, non-deleted activity before
    # any write happens. A missing id fails the whole call (no partial write).
    for aid in ids:
        activity = activity_service.get_activity(aid)
        if not activity:
            raise ValueError("activity_id does not exist")
        if int(activity.get("is_deleted") or 0):
            raise ValueError("activity_id does not exist")
    return ids


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
    project = project_service.get_project(pid)
    if not project:
        raise ValueError("project_id does not exist")
    return pid


def _validate_optional_project_id(project_id: int | None) -> int | None:
    if project_id is None:
        return None
    return _validate_project_id(project_id)


def _validate_activity_member_hash(activity_member_hash: str) -> str:
    if not isinstance(activity_member_hash, str):
        raise ValueError("activity_member_hash must be a string")
    value = activity_member_hash.strip()
    if len(value) != 40:
        raise ValueError("activity_member_hash must be a sha1 hex string")
    try:
        int(value, 16)
    except ValueError:
        raise ValueError("activity_member_hash must be a sha1 hex string")
    return value


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


def _find_session_by_identity(sessions: list[dict[str, Any]], ids: list[int], member_hash: str) -> dict[str, Any]:
    id_set = {int(aid) for aid in ids}
    for session in sessions:
        if str(session.get("activity_member_hash") or "") != member_hash:
            continue
        if {int(aid) for aid in session.get("activity_ids") or []} == id_set:
            return session
    raise ValueError("session_identity_conflict")


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
    "get_session_activity_details",
    "get_session_anchor_folders",
    "get_snapshot_elapsed_seconds",
    "get_snapshot_extra_seconds",
    "get_snapshot_persisted_id",
    "get_snapshot_seconds_for_date_range",
    "hide_timeline_session",
    "hide_timeline_session_activity",
    "list_selectable_projects",
    "preview_session_project_update",
    "copy_timeline_session",
    "merge_timeline_session",
    "save_timeline_session_override",
    "split_timeline_session",
    "update_timeline_session_note",
    "update_timeline_session_note_and_duration",
]
