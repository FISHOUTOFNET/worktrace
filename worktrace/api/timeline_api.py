"""Timeline, activity, and live-time facade for the UI.

Wraps ``timeline_service``, the activity-editing helpers from
``activity_service``, the project-selection helper from ``project_service``,
and the pure live-time helpers from ``live_time_service``.
"""

from __future__ import annotations

from typing import Any

from ..services import activity_service, project_service, timeline_service
from ..services.live_time_service import (
    is_unconfirmed_snapshot,
    short_activity_carry_duration,
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
    snapshot_signature,
    sync_short_activity_carry,
)


# --- timeline / sessions -------------------------------------------------

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


def update_session_project(session_activity_ids: list[int], project_id: int) -> None:
    timeline_service.update_session_project(session_activity_ids, project_id)


def update_session_note(report_date: str, first_activity_id: int, note: str) -> None:
    timeline_service.update_session_note(report_date, first_activity_id, note)


def update_activity_group_project(activity_ids: list[int], project_id: int) -> None:
    timeline_service.update_activity_group_project(activity_ids, project_id)


def preview_session_project_update(
    session_activity_ids: list[int],
    project_id: int,
) -> dict[str, Any]:
    return timeline_service.preview_session_project_update(session_activity_ids, project_id)


# --- Phase 3A: validated Timeline editing (project reclassification + note) ---

# Maximum length for a session note. The existing ``project_session_note``
# table has no length constraint, so the API enforces a reasonable upper
# bound to keep the WebView editing surface bounded and testable.
TIMELINE_NOTE_MAX_LENGTH = 2000


def reclassify_timeline_session_project(
    activity_ids: list[int],
    project_id: int,
) -> None:
    """Validate and apply a project reclassification to a Timeline session.

    Reclassifies every activity in ``activity_ids`` to ``project_id`` as a
    manual assignment. This mirrors the legacy Tkinter ``update_session_project``
    behavior (all activities in the session move together) but adds explicit
    input validation so the WebView bridge never performs a partial or
    invalid write.

    Validation:
    - ``activity_ids`` must be a non-empty list of positive integers; every
      id must reference an existing, non-deleted activity. If any id is
      missing the whole call raises ``ValueError`` before any write.
    - ``project_id`` must be a positive integer referencing an existing
      project. "未归类" is represented by the existing system
      ``UNCATEGORIZED_PROJECT`` row id (surfaced via
      ``list_selectable_projects``), never by ``None``.

    Raises ``ValueError`` on any invalid input. The underlying service write
    is atomic (single transaction), so a validated call either fully
    succeeds or fully rolls back.
    """
    ids = _validate_activity_ids(activity_ids)
    pid = _validate_project_id(project_id)
    timeline_service.update_session_project(ids, pid)


def update_timeline_session_note(
    report_date: str,
    first_activity_id: int,
    note: str,
) -> None:
    """Validate and write a session note for the Timeline page.

    The session note is stored in ``project_session_note`` keyed by
    ``(report_date, first_activity_id)`` — the same model the legacy Tkinter
    Timeline uses. ``first_activity_id`` is the first activity id of the
    session (``activity_ids[0]``).

    Validation:
    - ``report_date`` must be a ``YYYY-MM-DD`` string.
    - ``first_activity_id`` must be a positive integer referencing an
      existing, non-deleted activity.
    - ``note`` must be a string. It is stripped; the stripped value must not
      exceed ``TIMELINE_NOTE_MAX_LENGTH`` characters. Whitespace-only notes
      are treated as empty and delete the existing note row (matching the
      legacy ``set_session_note`` behavior). Legitimate newlines inside the
      note are preserved.

    Raises ``ValueError`` on any invalid input.
    """
    date = _validate_report_date(report_date)
    first_id = _validate_first_activity_id(first_activity_id)
    text = _validate_note(note)
    timeline_service.update_session_note(date, first_id, text)


def _validate_activity_ids(activity_ids: list[int]) -> list[int]:
    if not isinstance(activity_ids, list) or not activity_ids:
        raise ValueError("activity_ids must be a non-empty list")
    ids: list[int] = []
    seen: set[int] = set()
    for raw in activity_ids:
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


def _validate_report_date(report_date: str) -> str:
    from datetime import date as date_type

    if not isinstance(report_date, str) or not report_date:
        raise ValueError("report_date must be a YYYY-MM-DD string")
    try:
        date_type.fromisoformat(report_date)
    except ValueError:
        raise ValueError("report_date must be a YYYY-MM-DD string")
    return report_date


def _validate_first_activity_id(first_activity_id: int) -> int:
    try:
        first_id = int(first_activity_id)
    except (TypeError, ValueError):
        raise ValueError("first_activity_id must be an integer")
    if first_id <= 0:
        raise ValueError("first_activity_id must be a positive integer")
    activity = activity_service.get_activity(first_id)
    if not activity:
        raise ValueError("first_activity_id does not exist")
    if int(activity.get("is_deleted") or 0):
        raise ValueError("first_activity_id does not exist")
    return first_id


def _validate_note(note: str) -> str:
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    if len(note) > TIMELINE_NOTE_MAX_LENGTH:
        raise ValueError("note exceeds maximum length")
    return note


# --- activity editing ----------------------------------------------------

def update_activity_note(activity_id: int, note: str) -> None:
    activity_service.update_activity_note(activity_id, note)


def soft_delete_activity(activity_id: int) -> None:
    activity_service.soft_delete_activity(activity_id)


# --- project selection (for timeline menus) ------------------------------

def list_selectable_projects() -> list[dict[str, Any]]:
    return project_service.list_selectable_projects()


# --- live-time helpers (pure functions over snapshot dicts) --------------

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


def get_snapshot_signature(snapshot: dict[str, Any] | None) -> tuple | None:
    return snapshot_signature(snapshot)


def sync_short_activity_carry_value(
    carry: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return sync_short_activity_carry(carry, previous, current)


def get_short_activity_carry_duration(
    carry: dict[str, Any] | None,
    activity_ids: list[int],
    duration_seconds: int,
    report_date: str,
    snapshot: dict[str, Any] | None,
) -> int | None:
    return short_activity_carry_duration(
        carry,
        activity_ids,
        duration_seconds,
        report_date,
        snapshot,
    )


def is_snapshot_unconfirmed(snapshot: dict[str, Any] | None) -> bool:
    return is_unconfirmed_snapshot(snapshot)


__all__ = [
    "TIMELINE_NOTE_MAX_LENGTH",
    "get_default_report_date",
    "get_project_sessions_by_date",
    "get_project_sessions_by_range",
    "get_session_activity_details",
    "get_session_anchor_folders",
    "get_short_activity_carry_duration",
    "get_snapshot_elapsed_seconds",
    "get_snapshot_extra_seconds",
    "get_snapshot_persisted_id",
    "get_snapshot_seconds_for_date_range",
    "get_snapshot_signature",
    "is_snapshot_unconfirmed",
    "list_selectable_projects",
    "preview_session_project_update",
    "reclassify_timeline_session_project",
    "soft_delete_activity",
    "sync_short_activity_carry_value",
    "update_activity_group_project",
    "update_activity_note",
    "update_session_note",
    "update_session_project",
    "update_timeline_session_note",
]
