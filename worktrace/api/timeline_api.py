"""Timeline, activity, and live-time facade for the UI.

Wraps ``timeline_service``, the activity-editing helpers from
``activity_service``, the project-selection helper from ``project_service``,
and the pure live-time helpers from ``live_time_service``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..constants import TIME_FORMAT
from ..services import activity_service, project_service, timeline_service
from ..services.activity_edit_policy import project_editability_code
from ..services.live_time_service import (
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
)

NOT_PROJECT_ACTIVITY_CODE = "not_project_activity"


class TimelineTimeEditError(ValueError):
    """Raised by the time-correction methods for known user-facing failures.

    The ``code`` attribute is a stable token the WebView bridge maps to a
    Chinese message, so internal field names, ids, and SQL details never
    reach the bridge. The bridge catches this separately from generic
    ``ValueError`` so unknown validation failures still collapse to the
    generic ``"操作失败"`` message.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TimelineSplitError(ValueError):
    """Raised by the activity-split methods for known user-facing failures.

    Stable ``code`` values mapped by the WebView bridge to Chinese messages:

    - ``invalid_id`` — not a positive int, ``bool``, missing, or deleted.
    - ``invalid_time`` — split_time is not a ``YYYY-MM-DD HH:MM:SS`` string.
    - ``outside_range`` — split_time is not strictly between start and end.
    - ``in_progress`` — the activity is still open (``end_time IS NULL``).
    - ``multi_activity`` — session-level split on a multi-activity session.
    - ``operation_failed`` — race condition or unexpected service failure.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TimelineMergeError(ValueError):
    """Raised by the activity-merge methods for known user-facing failures.

    Stable ``code`` values mapped by the WebView bridge to Chinese messages:

    - ``invalid_selection`` — activity_ids is not exactly two after dedup.
    - ``invalid_id`` — not a positive int, ``bool``, missing, or deleted.
    - ``in_progress`` — either activity is still open (``end_time IS NULL``).
    - ``different_project`` — the two activities have different project_id.
    - ``different_resource`` — the two activities have different resource
      identity_key.
    - ``incompatible_activity`` — status or source differs.
    - ``not_adjacent`` — the gap between the two activities exceeds
      ``MERGE_GAP_TOLERANCE_SECONDS``.
    - ``invalid_time`` — the two activities overlap in time.
    - ``operation_failed`` — race condition or unexpected service failure.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TimelineVisibilityError(ValueError):
    """Raised by the hide / soft-delete methods for known user-facing failures.

    Stable ``code`` values mapped by the WebView bridge to Chinese messages:

    - ``invalid_id`` — not a positive int, ``bool``, missing, or deleted.
    - ``in_progress`` — the activity is still open (``end_time IS NULL``).
    - ``multi_activity_hide`` — session-level hide on a multi-activity session.
    - ``multi_activity_delete`` — session-level delete on a multi-activity
      session.
    - ``operation_failed`` — race condition or unexpected service failure.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TimelineBatchProjectError(ValueError):
    """Raised by the batch project reassignment methods for known
    user-facing failures.

    Stable ``code`` values mapped by the WebView bridge to Chinese messages:

    - ``invalid_selection`` — activity_ids is not a list, contains fewer
      than 2 ids after dedup, or contains non-int / bool / non-positive
      values.
    - ``batch_too_large`` — the deduplicated id count exceeds
      ``MAX_BATCH_PROJECT_EDIT_ACTIVITIES`` (100).
    - ``invalid_project`` — project_id is not a positive int / bool, or the
      project does not exist / is archived / is disabled.
    - ``in_progress`` — any activity is still open (``end_time IS NULL``).
    - ``hidden_activity`` — any activity has ``is_hidden = 1``.
    - ``operation_failed`` — race condition or unexpected service failure
      (e.g. a row was deleted between validation and write).
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TimelineBatchNoteError(ValueError):
    """Raised by the batch note overwrite methods for known user-facing failures.

    Stable ``code`` values mapped by the WebView bridge to Chinese messages:

    - ``invalid_selection`` — activity_ids is not a list, contains fewer
      than 2 ids after dedup, or contains non-int / bool / non-positive
      values; also used when an activity is missing or already deleted.
    - ``batch_too_large`` — the deduplicated id count exceeds
      ``MAX_BATCH_NOTE_EDIT_ACTIVITIES`` (100).
    - ``invalid_note`` — note is not a ``str`` or is ``None``.
    - ``note_too_long`` — note exceeds ``BATCH_NOTE_MAX_LENGTH`` (2000).
    - ``in_progress`` — any activity is still open (``end_time IS NULL``).
    - ``hidden_activity`` — any activity has ``is_hidden = 1``.
    - ``operation_failed`` — race condition or unexpected service failure
      (e.g. a row was deleted between validation and write).
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TimelineRestoreActivityError(ValueError):
    """Raised by the single activity restore methods for known user-facing
    failures.

    Stable ``code`` values mapped by the WebView bridge to Chinese messages:

    - ``invalid_activity`` — activity_id is not a positive int or is ``bool``.
    - ``not_found`` — the activity does not exist.
    - ``not_restorable`` — the activity is neither hidden nor deleted.
    - ``in_progress`` — the activity is still open (``end_time IS NULL``).
    - ``operation_failed`` — race condition or unexpected service failure.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code



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


def update_activity_group_project(activity_ids: list[int], project_id: int) -> None:
    timeline_service.update_activity_group_project(activity_ids, project_id)


def preview_session_project_update(
    session_activity_ids: list[int],
    project_id: int,
) -> dict[str, Any]:
    return timeline_service.preview_session_project_update(session_activity_ids, project_id)



# Maximum length for a session note. The ``project_session_note`` table has
# no length constraint, so the API enforces a reasonable upper bound to
# keep the WebView editing surface bounded and testable.
TIMELINE_NOTE_MAX_LENGTH = 2000

# Maximum allowed value for ``adjusted_duration_seconds``. A single day has
# 86400 seconds; allowing up to that keeps the override sane without
# rejecting long but legitimate sessions.
TIMELINE_ADJUSTED_DURATION_MAX_SECONDS = 24 * 60 * 60


def reclassify_timeline_session_project(
    activity_ids: list[int],
    project_id: int,
) -> None:
    """Validate and apply a project reclassification to a Timeline session."""
    ids = _validate_activity_ids(activity_ids)
    pid = _validate_project_id(project_id)
    for aid in ids:
        _ensure_project_editable_for_value_error(activity_service.get_activity(aid))
    timeline_service.update_session_project(ids, pid)


def update_timeline_session_note(
    report_date: str,
    first_activity_id: int,
    note: str,
) -> None:
    """Validate and write a session note for the Timeline page.

    The session note is stored in ``project_session_note`` keyed by
    ``(report_date, first_activity_id)``. ``first_activity_id`` is the
    first activity id of the session (``activity_ids[0]``).

    Validation:
    - ``report_date`` must be a ``YYYY-MM-DD`` string.
    - ``first_activity_id`` must be a positive integer referencing an
      existing, non-deleted activity.
    - ``note`` must be a string. It is stripped; the stripped value must not
      exceed ``TIMELINE_NOTE_MAX_LENGTH`` characters. Whitespace-only notes
      are treated as empty and delete the existing note row. Legitimate
      newlines remain intact.

    Raises ``ValueError`` on any invalid input.
    """
    date = _validate_report_date(report_date)
    first_id = _validate_first_activity_id(first_activity_id)
    text = _validate_note(note)
    _ensure_project_editable_for_value_error(activity_service.get_activity(first_id))
    timeline_service.update_session_note(date, first_id, text)


def update_timeline_session_note_and_duration(
    report_date: str,
    first_activity_id: int,
    note: str,
    adjusted_duration_seconds: int | None,
) -> None:
    """Validate and write note + user-adjusted duration for a Timeline session."""
    date = _validate_report_date(report_date)
    first_id = _validate_first_activity_id(first_activity_id)
    text = _validate_note(note)
    duration = _validate_adjusted_duration(adjusted_duration_seconds)
    _ensure_project_editable_for_value_error(activity_service.get_activity(first_id))
    timeline_service.update_session_note_and_duration(date, first_id, text, duration)




def update_timeline_activity_time(
    activity_id: int,
    start_time: str,
    end_time: str,
) -> None:
    """Validate and apply a time correction to a single activity.

    Validation:
    - ``activity_id`` must be a positive integer (``bool`` rejected); it must
      reference an existing, non-deleted, non-in-progress activity.
    - ``start_time`` and ``end_time`` must be ``YYYY-MM-DD HH:MM:SS`` strings.
    - ``start_time < end_time`` (zero and negative durations rejected).

    Raises ``TimelineTimeEditError`` with a stable ``code`` for known
    failure modes (``invalid_id``, ``invalid_time``, ``in_progress``). The
    write is a single atomic UPDATE; no partial writes are possible.
    """
    aid = _validate_activity_id_for_time_edit(activity_id)
    start = _validate_time_string(start_time)
    end = _validate_time_string(end_time)
    _validate_time_order(start, end)
    try:
        activity_service.update_activity_time(aid, start, end)
    except ValueError:
        # Defensive: the activity was deleted or reopened between validation
        # and write (race condition). Treat as invalid_id so the bridge
        # returns a clear message instead of silently succeeding.
        raise TimelineTimeEditError("invalid_id")


def update_timeline_session_time(
    activity_ids: list[int],
    start_time: str,
    end_time: str,
) -> None:
    """Validate and apply a session-level time correction."""
    ids = _validate_activity_ids(activity_ids)
    start = _validate_time_string(start_time)
    end = _validate_time_string(end_time)
    _validate_time_order(start, end)
    if len(ids) > 1:
        raise TimelineTimeEditError("multi_activity")
    # Single activity: re-check in-progress (existence/deleted already done
    # by _validate_activity_ids, but the in-progress check is specific to
    # time editing and must not be skipped).
    activity = activity_service.get_activity(ids[0])
    _ensure_project_editable_for_time_error(activity)
    try:
        activity_service.update_activity_time(ids[0], start, end)
    except ValueError:
        # Defensive: race condition between validation and write.
        raise TimelineTimeEditError("invalid_id")




def split_timeline_activity(activity_id: int, split_time: str) -> dict:
    """Validate and split a single closed activity at ``split_time``.

    Validation:
    - ``activity_id`` must be a positive integer (``bool`` rejected); it must
      reference an existing, non-deleted, non-in-progress activity.
    - ``split_time`` must be a ``YYYY-MM-DD HH:MM:SS`` string strictly
      between the activity's ``start_time`` and ``end_time``.

    Returns ``{"original_activity_id": int, "new_activity_id": int}`` on
    success. Raises ``TimelineSplitError`` with a stable ``code`` for known
    failure modes. The write is a single atomic transaction; no partial
    writes are possible.
    """
    aid = _validate_activity_id_for_split(activity_id)
    split = _validate_time_string_for_split(split_time)
    activity = activity_service.get_activity(aid)
    # Re-check end_time after fetching (the existence/deleted check is done
    # in _validate_activity_id_for_split, but the in-progress check must use
    # the raw DB end_time, not a projected display value).
    _ensure_project_editable_for_split_error(activity)
    start = activity["start_time"]
    end = activity["end_time"]
    _validate_split_range(split, start, end)
    try:
        return activity_service.split_activity(aid, split)
    except ValueError as exc:
        if str(exc) == "activity_not_project_activity":
            raise TimelineSplitError(NOT_PROJECT_ACTIVITY_CODE)
        # Defensive: race condition (deleted/reopened between validation and
        # write) or split_time fell outside the range due to a concurrent
        # time edit. Treat as operation_failed so the bridge returns a clear
        # message without echoing internal details.
        raise TimelineSplitError("operation_failed")


def split_timeline_session(activity_ids: list[int], split_time: str) -> dict:
    """Validate and apply a session-level split."""
    ids = _validate_activity_ids(activity_ids)
    split = _validate_time_string_for_split(split_time)
    if len(ids) > 1:
        raise TimelineSplitError("multi_activity")
    activity = activity_service.get_activity(ids[0])
    _ensure_project_editable_for_split_error(activity)
    _validate_split_range(split, activity["start_time"], activity["end_time"])
    try:
        return activity_service.split_activity(ids[0], split)
    except ValueError as exc:
        if str(exc) == "activity_not_project_activity":
            raise TimelineSplitError(NOT_PROJECT_ACTIVITY_CODE)
        raise TimelineSplitError("operation_failed")


def _validate_activity_id_for_split(activity_id: int) -> int:
    """Validate a single ``activity_id`` for split (existence and deleted
    state only).

    Returns the validated positive int. Raises ``TimelineSplitError``:
    - ``invalid_id`` — not a positive int, ``bool``, missing, or deleted.

    The in-progress check (``end_time IS NULL``) is deliberately performed
    in ``split_timeline_activity`` / ``split_timeline_session`` after this
    validator returns, because those callers also need to fetch the
    activity row for the split-range check. Performing the in-progress
    check there avoids a double fetch and reads the raw ``end_time`` from
    the row (not a projected display value), so it correctly reflects the
    DB state.
    """
    if isinstance(activity_id, bool):
        raise TimelineSplitError("invalid_id")
    try:
        aid = int(activity_id)
    except (TypeError, ValueError):
        raise TimelineSplitError("invalid_id")
    if aid <= 0:
        raise TimelineSplitError("invalid_id")
    activity = activity_service.get_activity(aid)
    code = _project_editability_code(activity)
    if code == "invalid_id":
        raise TimelineSplitError("invalid_id")
    if code == "hidden_activity":
        raise TimelineSplitError("invalid_id")
    if code == "in_progress":
        raise TimelineSplitError("in_progress")
    if code == NOT_PROJECT_ACTIVITY_CODE:
        raise TimelineSplitError(NOT_PROJECT_ACTIVITY_CODE)
    return aid


def _validate_time_string_for_split(value: str) -> str:
    """Validate a ``YYYY-MM-DD HH:MM:SS`` split_time string.

    Raises ``TimelineSplitError("invalid_time")`` if the value is not a
    non-empty string or does not parse against ``TIME_FORMAT``.
    """
    if not isinstance(value, str) or not value:
        raise TimelineSplitError("invalid_time")
    try:
        datetime.strptime(value, TIME_FORMAT)
    except ValueError:
        raise TimelineSplitError("invalid_time")
    return value


def _validate_split_range(split_time: str, start_time: str, end_time: str) -> None:
    """Ensure ``start_time < split_time < end_time`` (strictly inside).

    All arguments must already be validated ``YYYY-MM-DD HH:MM:SS`` strings.
    Raises ``TimelineSplitError("outside_range")`` if the split point is not
    strictly between start and end (equal to either boundary is rejected, as
    it would produce a zero-duration half).
    """
    start_dt = datetime.strptime(start_time, TIME_FORMAT)
    split_dt = datetime.strptime(split_time, TIME_FORMAT)
    end_dt = datetime.strptime(end_time, TIME_FORMAT)
    if split_dt <= start_dt or split_dt >= end_dt:
        raise TimelineSplitError("outside_range")


# The write is a single atomic transaction; any failure rolls back.


def merge_timeline_activities(activity_ids: list[int]) -> dict:
    """Validate and merge exactly two closed activities into one."""
    ids = _validate_merge_activity_ids(activity_ids)
    if len(ids) != 2:
        raise TimelineMergeError("invalid_selection")
    try:
        return activity_service.merge_activities(ids[0], ids[1])
    except ValueError as exc:
        code = str(exc)
        # Map service-layer ValueError codes to stable TimelineMergeError
        # codes. The service raises ValueError with a descriptive suffix;
        # we map each known suffix to its stable code so internal details
        # never surface to the bridge.
        if code == "activity_merge_same_id":
            # After dedup this should not happen, but handle defensively.
            raise TimelineMergeError("invalid_selection")
        if code == "activity_merge_not_found_or_deleted":
            raise TimelineMergeError("invalid_id")
        if code == "activity_merge_in_progress":
            raise TimelineMergeError("in_progress")
        if code == "activity_merge_overlap":
            raise TimelineMergeError("invalid_time")
        if code == "activity_merge_not_adjacent":
            raise TimelineMergeError("not_adjacent")
        if code == "activity_merge_different_project":
            raise TimelineMergeError("different_project")
        if code == "activity_merge_different_resource":
            raise TimelineMergeError("different_resource")
        if code == "activity_merge_incompatible_activity":
            raise TimelineMergeError("incompatible_activity")
        if code == "activity_merge_not_project_activity":
            raise TimelineMergeError(NOT_PROJECT_ACTIVITY_CODE)
        # ``activity_merge_update_affected_zero_rows`` or any unexpected
        # ValueError collapses to ``operation_failed`` so the bridge returns
        # a clear generic message without echoing internal details.
        raise TimelineMergeError("operation_failed")


def _validate_merge_activity_ids(activity_ids: list[int]) -> list[int]:
    """Validate the ``activity_ids`` list for merge.

    Returns a deduplicated list of positive ints. Raises
    ``TimelineMergeError``:
    - ``invalid_selection`` — not a list, empty, or contains non-int /
      bool / non-positive values.
    - ``invalid_id`` — any id does not reference an existing, non-deleted
      activity.

    The caller (``merge_timeline_activities``) checks that exactly two ids
    remain after dedup.
    """
    if isinstance(activity_ids, bool) or not isinstance(activity_ids, list):
        raise TimelineMergeError("invalid_selection")
    if not activity_ids:
        raise TimelineMergeError("invalid_selection")
    ids: list[int] = []
    seen: set[int] = set()
    for raw in activity_ids:
        if isinstance(raw, bool):
            raise TimelineMergeError("invalid_selection")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise TimelineMergeError("invalid_selection")
        if value <= 0:
            raise TimelineMergeError("invalid_selection")
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    # Verify every id references an existing, non-deleted activity before
    # any write happens. A missing id fails the whole call (no partial write).
    for aid in ids:
        activity = activity_service.get_activity(aid)
        code = _project_editability_code(activity)
        if code in {"invalid_id", "hidden_activity"}:
            raise TimelineMergeError("invalid_id")
        if code == "in_progress":
            raise TimelineMergeError("in_progress")
        if code == NOT_PROJECT_ACTIVITY_CODE:
            raise TimelineMergeError(NOT_PROJECT_ACTIVITY_CODE)
    return ids




def hide_timeline_activity(activity_id: int) -> None:
    """Validate and hide a single closed activity.

    Validation:
    - ``activity_id`` must be a positive integer (``bool`` rejected); it must
      reference an existing, non-deleted, non-in-progress activity.

    Raises ``TimelineVisibilityError`` with a stable ``code`` for known
    failure modes (``invalid_id``, ``in_progress``, ``operation_failed``).
    The write is a single atomic UPDATE; no partial writes are possible.
    Hiding an already-hidden activity succeeds (idempotent).
    """
    aid = _validate_activity_id_for_visibility(activity_id)
    try:
        activity_service.hide_activity(aid)
    except ValueError:
        # Defensive: race condition (deleted/reopened between validation and
        # write). Treat as operation_failed so the bridge returns a clear
        # message without echoing internal details.
        raise TimelineVisibilityError("operation_failed")


def soft_delete_timeline_activity(activity_id: int) -> None:
    """Validate and soft-delete a single closed activity.

    Validation:
    - ``activity_id`` must be a positive integer (``bool`` rejected); it must
      reference an existing, non-deleted, non-in-progress activity.

    Raises ``TimelineVisibilityError`` with a stable ``code`` for known
    failure modes (``invalid_id``, ``in_progress``, ``operation_failed``).
    The write is a single atomic UPDATE; no partial writes are possible.
    """
    aid = _validate_activity_id_for_visibility(activity_id)
    try:
        activity_service.soft_delete_activity(aid)
    except ValueError:
        raise TimelineVisibilityError("operation_failed")


def hide_timeline_session(activity_ids: list[int]) -> None:
    """Validate and apply a session-level hide."""
    ids = _validate_visibility_activity_ids(activity_ids)
    if len(ids) > 1:
        raise TimelineVisibilityError("multi_activity_hide")
    activity = activity_service.get_activity(ids[0])
    if activity.get("end_time") is None:
        raise TimelineVisibilityError("in_progress")
    try:
        activity_service.hide_activity(ids[0])
    except ValueError:
        raise TimelineVisibilityError("operation_failed")


def soft_delete_timeline_session(activity_ids: list[int]) -> None:
    """Validate and apply a session-level soft delete."""
    ids = _validate_visibility_activity_ids(activity_ids)
    if len(ids) > 1:
        raise TimelineVisibilityError("multi_activity_delete")
    activity = activity_service.get_activity(ids[0])
    if activity.get("end_time") is None:
        raise TimelineVisibilityError("in_progress")
    try:
        activity_service.soft_delete_activity(ids[0])
    except ValueError:
        raise TimelineVisibilityError("operation_failed")


def _validate_activity_id_for_visibility(activity_id: int) -> int:
    """Validate a single ``activity_id`` for hide / soft delete.

    Returns the validated positive int. Raises ``TimelineVisibilityError``:
    - ``invalid_id`` — not a positive int, ``bool``, missing, or deleted.
    - ``in_progress`` — the activity is still open (``end_time IS NULL``).

    The in-progress check reads the raw ``end_time`` from the row (not a
    projected display value), so it correctly reflects the DB state.
    """
    if isinstance(activity_id, bool):
        raise TimelineVisibilityError("invalid_id")
    try:
        aid = int(activity_id)
    except (TypeError, ValueError):
        raise TimelineVisibilityError("invalid_id")
    if aid <= 0:
        raise TimelineVisibilityError("invalid_id")
    activity = activity_service.get_activity(aid)
    if not activity or int(activity.get("is_deleted") or 0):
        raise TimelineVisibilityError("invalid_id")
    if activity.get("end_time") is None:
        raise TimelineVisibilityError("in_progress")
    return aid


def _validate_visibility_activity_ids(activity_ids: list[int]) -> list[int]:
    """Validate the ``activity_ids`` list for session-level hide / soft delete.

    Returns a deduplicated list of positive ints. Raises
    ``TimelineVisibilityError``:
    - ``invalid_id`` — not a list, empty, contains non-int / bool /
      non-positive values, or any id does not reference an existing,
      non-deleted activity.

    The caller checks that exactly one id remains after dedup.
    """
    if isinstance(activity_ids, bool) or not isinstance(activity_ids, list):
        raise TimelineVisibilityError("invalid_id")
    if not activity_ids:
        raise TimelineVisibilityError("invalid_id")
    ids: list[int] = []
    seen: set[int] = set()
    for raw in activity_ids:
        if isinstance(raw, bool):
            raise TimelineVisibilityError("invalid_id")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise TimelineVisibilityError("invalid_id")
        if value <= 0:
            raise TimelineVisibilityError("invalid_id")
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    for aid in ids:
        activity = activity_service.get_activity(aid)
        if not activity or int(activity.get("is_deleted") or 0):
            raise TimelineVisibilityError("invalid_id")
    return ids


# Batch project edits are atomic and only accept closed visible activities.


def batch_update_timeline_activities_project(
    activity_ids: list[int],
    project_id: int,
) -> dict:
    """Validate and apply a batch project reassignment to multiple activities.

    Validation:
    - ``activity_ids`` must be a list of positive integers (``bool``
      rejected); duplicate ids are deduplicated. After deduplication, at
      least 2 ids must remain and the count must not exceed
      ``MAX_BATCH_PROJECT_EDIT_ACTIVITIES``.
    - ``project_id`` must be a positive integer (``bool`` rejected) and
      must reference an existing, non-archived, enabled project.
    - Every activity must exist, be non-deleted, non-hidden, and closed
      (``end_time IS NOT NULL``).

    Returns ``{"updated_count": int}`` on success. Raises
    ``TimelineBatchProjectError`` with a stable ``code`` for known failure
    modes. The write is a single atomic transaction; no partial writes are
    possible.
    """
    ids = _validate_batch_activity_ids(activity_ids)
    pid = _validate_batch_project_id(project_id)
    try:
        count = activity_service.batch_update_activity_project(ids, pid)
    except ValueError as exc:
        code = str(exc)
        if code == "invalid_activity_ids":
            raise TimelineBatchProjectError("invalid_selection")
        if code == "batch_too_large":
            raise TimelineBatchProjectError("batch_too_large")
        if code == "invalid_project":
            raise TimelineBatchProjectError("invalid_project")
        if code == "activity_not_found":
            raise TimelineBatchProjectError("invalid_selection")
        if code == "activity_deleted":
            raise TimelineBatchProjectError("invalid_selection")
        if code == "activity_hidden":
            raise TimelineBatchProjectError("hidden_activity")
        if code == "activity_in_progress":
            raise TimelineBatchProjectError("in_progress")
        if code == "activity_not_project_activity":
            raise TimelineBatchProjectError(NOT_PROJECT_ACTIVITY_CODE)
        # ``project_update_failed`` or any unexpected ValueError collapses
        # to ``operation_failed`` so the bridge returns a clear generic
        # message without echoing internal details.
        raise TimelineBatchProjectError("operation_failed")
    except Exception:
        # A non-ValueError service exception (e.g.
        # ``sqlite3.OperationalError``, ``RuntimeError``) must also collapse
        # to ``operation_failed`` so the bridge returns a clear generic
        # message without echoing internal details or tracebacks.
        raise TimelineBatchProjectError("operation_failed")
    return {"updated_count": int(count)}


def _validate_batch_activity_ids(activity_ids: list[int]) -> list[int]:
    """Validate the ``activity_ids`` list for batch project editing.

    Returns a deduplicated list of positive ints. Raises
    ``TimelineBatchProjectError``:
    - ``invalid_selection`` — not a list, empty, contains non-int / bool /
      non-positive values, or fewer than 2 ids after dedup.
    - ``batch_too_large`` — deduplicated count exceeds the max.
    """
    if isinstance(activity_ids, bool) or not isinstance(activity_ids, list):
        raise TimelineBatchProjectError("invalid_selection")
    if not activity_ids:
        raise TimelineBatchProjectError("invalid_selection")
    ids: list[int] = []
    seen: set[int] = set()
    for raw in activity_ids:
        if isinstance(raw, bool):
            raise TimelineBatchProjectError("invalid_selection")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise TimelineBatchProjectError("invalid_selection")
        if value <= 0:
            raise TimelineBatchProjectError("invalid_selection")
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    if len(ids) < 2:
        raise TimelineBatchProjectError("invalid_selection")
    if len(ids) > activity_service.MAX_BATCH_PROJECT_EDIT_ACTIVITIES:
        raise TimelineBatchProjectError("batch_too_large")
    return ids


def _validate_batch_project_id(project_id: int) -> int:
    """Validate ``project_id`` for batch project editing.

    Returns the validated positive int. Raises ``TimelineBatchProjectError``:
    - ``invalid_project`` — not a positive int, ``bool``, or the project
      does not exist / is archived / is disabled.
    """
    if isinstance(project_id, bool):
        raise TimelineBatchProjectError("invalid_project")
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        raise TimelineBatchProjectError("invalid_project")
    if pid <= 0:
        raise TimelineBatchProjectError("invalid_project")
    project = project_service.get_project(pid)
    if not project:
        raise TimelineBatchProjectError("invalid_project")
    if int(project.get("is_archived") or 0) or not int(project.get("enabled") or 0):
        raise TimelineBatchProjectError("invalid_project")
    return pid


# value in a single atomic transaction.


def batch_update_timeline_activities_note(
    activity_ids: list[int],
    note: str,
) -> dict:
    """Validate and apply a batch note overwrite to multiple activities.

    Validation:
    - ``activity_ids`` must be a list of positive integers (``bool``
      rejected); duplicate ids are deduplicated. After deduplication, at
      least 2 ids must remain and the count must not exceed
      ``MAX_BATCH_NOTE_EDIT_ACTIVITIES``.
    - ``note`` must be a ``str`` (``None`` rejected). Empty string is
      allowed (used to batch-clear notes). The length must not exceed
      ``BATCH_NOTE_MAX_LENGTH``.
    - Every activity must exist, be non-deleted, non-hidden, and closed
      (``end_time IS NOT NULL``).

    Returns ``{"updated_count": int}`` on success. Raises
    ``TimelineBatchNoteError`` with a stable ``code`` for known failure
    modes. The write is a single atomic transaction; no partial writes are
    possible.
    """
    ids = _validate_batch_note_activity_ids(activity_ids)
    text = _validate_batch_note(note)
    try:
        count = activity_service.batch_update_activity_note(ids, text)
    except ValueError as exc:
        code = str(exc)
        if code == "invalid_activity_ids":
            raise TimelineBatchNoteError("invalid_selection")
        if code == "batch_too_large":
            raise TimelineBatchNoteError("batch_too_large")
        if code == "invalid_note":
            raise TimelineBatchNoteError("invalid_note")
        if code == "note_too_long":
            raise TimelineBatchNoteError("note_too_long")
        if code == "activity_not_found":
            raise TimelineBatchNoteError("invalid_selection")
        if code == "activity_deleted":
            raise TimelineBatchNoteError("invalid_selection")
        if code == "activity_hidden":
            raise TimelineBatchNoteError("hidden_activity")
        if code == "activity_in_progress":
            raise TimelineBatchNoteError("in_progress")
        if code == "activity_not_project_activity":
            raise TimelineBatchNoteError(NOT_PROJECT_ACTIVITY_CODE)
        # ``note_update_failed`` or any unexpected ValueError collapses
        # to ``operation_failed`` so the bridge returns a clear generic
        # message without echoing internal details.
        raise TimelineBatchNoteError("operation_failed")
    except Exception:
        # A non-ValueError service exception (e.g. ``sqlite3.OperationalError``,
        # ``RuntimeError``) must also collapse to ``operation_failed`` so the
        # bridge returns a clear generic message without echoing internal
        # details or tracebacks.
        raise TimelineBatchNoteError("operation_failed")
    return {"updated_count": int(count)}


def _validate_batch_note_activity_ids(activity_ids: list[int]) -> list[int]:
    """Validate the ``activity_ids`` list for batch note editing.

    Returns a deduplicated list of positive ints. Raises
    ``TimelineBatchNoteError``:
    - ``invalid_selection`` — not a list, empty, contains non-int / bool /
      non-positive values, or fewer than 2 ids after dedup.
    - ``batch_too_large`` — deduplicated count exceeds the max.
    """
    if isinstance(activity_ids, bool) or not isinstance(activity_ids, list):
        raise TimelineBatchNoteError("invalid_selection")
    if not activity_ids:
        raise TimelineBatchNoteError("invalid_selection")
    ids: list[int] = []
    seen: set[int] = set()
    for raw in activity_ids:
        if isinstance(raw, bool):
            raise TimelineBatchNoteError("invalid_selection")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise TimelineBatchNoteError("invalid_selection")
        if value <= 0:
            raise TimelineBatchNoteError("invalid_selection")
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    if len(ids) < 2:
        raise TimelineBatchNoteError("invalid_selection")
    if len(ids) > activity_service.MAX_BATCH_NOTE_EDIT_ACTIVITIES:
        raise TimelineBatchNoteError("batch_too_large")
    return ids


def _validate_batch_note(note: str) -> str:
    """Validate ``note`` for batch note editing.

    Returns the validated string. Raises ``TimelineBatchNoteError``:
    - ``invalid_note`` — not a ``str`` or is ``None``.
    - ``note_too_long`` — length exceeds ``BATCH_NOTE_MAX_LENGTH``.

    Empty string is allowed (used to batch-clear notes).
    """
    if not isinstance(note, str):
        raise TimelineBatchNoteError("invalid_note")
    if len(note) > activity_service.BATCH_NOTE_MAX_LENGTH:
        raise TimelineBatchNoteError("note_too_long")
    return note




def restore_timeline_activity(activity_id: int) -> dict:
    """Validate and restore a single hidden or soft-deleted activity.

    Validation:
    - ``activity_id`` must be a positive integer (``bool`` rejected); it
      must reference an existing activity that is hidden (``is_hidden = 1``)
      or soft-deleted (``is_deleted = 1``) and closed (raw
      ``end_time IS NOT NULL``).

    Returns ``{"restored": True, "activity_id": int}`` on success. Raises
    ``TimelineRestoreActivityError`` with a stable ``code`` for known
    failure modes. The write is a single atomic UPDATE; no partial writes
    are possible.
    """
    aid = _validate_activity_id_for_restore(activity_id)
    try:
        return activity_service.restore_activity(aid)
    except ValueError as exc:
        code = str(exc)
        if code == "invalid_activity_id":
            raise TimelineRestoreActivityError("invalid_activity")
        if code == "activity_not_found":
            raise TimelineRestoreActivityError("not_found")
        if code == "activity_not_restorable":
            raise TimelineRestoreActivityError("not_restorable")
        if code == "activity_in_progress":
            raise TimelineRestoreActivityError("in_progress")
        # ``restore_failed`` or any unexpected ValueError collapses to
        # ``operation_failed`` so the bridge returns a clear generic
        # message without echoing internal details.
        raise TimelineRestoreActivityError("operation_failed")
    except Exception:
        # A non-ValueError service exception must also collapse to
        # ``operation_failed`` so the bridge returns a clear generic
        # message without echoing internal details or tracebacks.
        raise TimelineRestoreActivityError("operation_failed")


def get_timeline_restorable_activities(date: str) -> dict:
    """Return a display-safe recovery list for a date.

    Returns ``{"activities": [...]}`` where each item has display-safe
    fields only (no raw ``window_title``, ``file_path_hint``,
    ``full_path``, ``clipboard``, ``note``, or exception details). Only
    hidden / deleted closed activities are returned, sorted by
    ``start_time``.

    Raises ``TimelineRestoreActivityError("invalid_date")`` if ``date``
    is not a ``YYYY-MM-DD`` string. The read path performs no writes and
    introduces no new DB schema.
    """
    if not isinstance(date, str) or not date:
        raise TimelineRestoreActivityError("invalid_date")
    try:
        items = activity_service.list_restorable_activities_for_date(date)
    except ValueError:
        raise TimelineRestoreActivityError("invalid_date")
    except Exception:
        # Any unexpected service exception collapses to ``operation_failed``
        # so the bridge returns a clear generic message without echoing
        # internal details or tracebacks.
        raise TimelineRestoreActivityError("operation_failed")
    return {"activities": items}


def _validate_activity_id_for_restore(activity_id: int) -> int:
    """Validate a single ``activity_id`` for restore.

    Returns the validated positive int. Raises ``TimelineRestoreActivityError``:
    - ``invalid_activity`` — not a positive int or ``bool``.

    The deeper existence / restorable / in-progress checks are performed
    by the service layer (``restore_activity``) so a single fetch is used
    for both validation and write; this avoids a double fetch and keeps
    the race-condition window minimal.
    """
    if isinstance(activity_id, bool):
        raise TimelineRestoreActivityError("invalid_activity")
    try:
        aid = int(activity_id)
    except (TypeError, ValueError):
        raise TimelineRestoreActivityError("invalid_activity")
    if aid <= 0:
        raise TimelineRestoreActivityError("invalid_activity")
    return aid


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
    if isinstance(first_activity_id, bool):
        raise ValueError("first_activity_id must be an integer")
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




def _validate_activity_id_for_time_edit(activity_id: int) -> int:
    """Validate a single ``activity_id`` for time correction.

    Returns the validated positive int. Raises ``TimelineTimeEditError``:
    - ``invalid_id`` — not a positive int, ``bool``, missing, or deleted.
    - ``in_progress`` — the activity is still open (``end_time IS NULL``).

    The in-progress check reads the raw ``end_time`` from the row (not a
    projected display value), so it correctly reflects the DB state.
    """
    if isinstance(activity_id, bool):
        raise TimelineTimeEditError("invalid_id")
    try:
        aid = int(activity_id)
    except (TypeError, ValueError):
        raise TimelineTimeEditError("invalid_id")
    if aid <= 0:
        raise TimelineTimeEditError("invalid_id")
    activity = activity_service.get_activity(aid)
    code = _project_editability_code(activity)
    if code == "invalid_id":
        raise TimelineTimeEditError("invalid_id")
    if code == "hidden_activity":
        raise TimelineTimeEditError("invalid_id")
    if code == "in_progress":
        raise TimelineTimeEditError("in_progress")
    if code == NOT_PROJECT_ACTIVITY_CODE:
        raise TimelineTimeEditError(NOT_PROJECT_ACTIVITY_CODE)
    return aid


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


def _ensure_project_editable_for_time_error(activity: dict | None) -> None:
    code = _project_editability_code(activity)
    if code in {"invalid_id", "hidden_activity"}:
        raise TimelineTimeEditError("invalid_id")
    if code == "in_progress":
        raise TimelineTimeEditError("in_progress")
    if code == NOT_PROJECT_ACTIVITY_CODE:
        raise TimelineTimeEditError(NOT_PROJECT_ACTIVITY_CODE)


def _ensure_project_editable_for_split_error(activity: dict | None) -> None:
    code = _project_editability_code(activity)
    if code in {"invalid_id", "hidden_activity"}:
        raise TimelineSplitError("invalid_id")
    if code == "in_progress":
        raise TimelineSplitError("in_progress")
    if code == NOT_PROJECT_ACTIVITY_CODE:
        raise TimelineSplitError(NOT_PROJECT_ACTIVITY_CODE)


def _validate_time_string(value: str) -> str:
    """Validate a ``YYYY-MM-DD HH:MM:SS`` time string.

    Raises ``TimelineTimeEditError("invalid_time")`` if the value is not a
    non-empty string or does not parse against ``TIME_FORMAT``.
    """
    if not isinstance(value, str) or not value:
        raise TimelineTimeEditError("invalid_time")
    try:
        datetime.strptime(value, TIME_FORMAT)
    except ValueError:
        raise TimelineTimeEditError("invalid_time")
    return value


def _validate_time_order(start_time: str, end_time: str) -> None:
    """Ensure ``start_time < end_time`` (zero and negative durations rejected).

    Both arguments must already be validated ``YYYY-MM-DD HH:MM:SS`` strings.
    """
    start_dt = datetime.strptime(start_time, TIME_FORMAT)
    end_dt = datetime.strptime(end_time, TIME_FORMAT)
    if end_dt <= start_dt:
        raise TimelineTimeEditError("invalid_time")



def soft_delete_activity(activity_id: int) -> None:
    activity_service.soft_delete_activity(activity_id)



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
    "TimelineBatchNoteError",
    "TimelineBatchProjectError",
    "TimelineRestoreActivityError",
    "TimelineTimeEditError",
    "TimelineSplitError",
    "TimelineMergeError",
    "TimelineVisibilityError",
    "batch_update_timeline_activities_note",
    "batch_update_timeline_activities_project",
    "get_default_report_date",
    "get_project_sessions_by_date",
    "get_project_sessions_by_range",
    "get_session_activity_details",
    "get_session_anchor_folders",
    "get_snapshot_elapsed_seconds",
    "get_snapshot_extra_seconds",
    "get_snapshot_persisted_id",
    "get_snapshot_seconds_for_date_range",
    "get_timeline_restorable_activities",
    "hide_timeline_activity",
    "hide_timeline_session",
    "list_selectable_projects",
    "merge_timeline_activities",
    "preview_session_project_update",
    "reclassify_timeline_session_project",
    "restore_timeline_activity",
    "soft_delete_activity",
    "soft_delete_timeline_activity",
    "soft_delete_timeline_session",
    "split_timeline_activity",
    "split_timeline_session",
    "update_activity_group_project",
    "update_session_project",
    "update_timeline_activity_time",
    "update_timeline_session_note",
    "update_timeline_session_note_and_duration",
    "update_timeline_session_time",
]
