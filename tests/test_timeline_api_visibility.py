"""Tests for the Timeline hide / soft-delete API and service layer.

Covers ``worktrace.api.timeline_api.hide_timeline_activity``,
``soft_delete_timeline_activity``, ``hide_timeline_session``,
``soft_delete_timeline_session`` and the underlying
``worktrace.services.activity_service.hide_activity`` /
``soft_delete_activity`` writes:

- input validation (bool id, non-int id, non-positive id, nonexistent id,
  deleted activity, in-progress activity, non-list session input, empty
  list, bool id in list, non-positive id in list, nonexistent id in list,
  deleted id in list);
- successful hide (sets ``is_hidden = 1``, idempotent, does not modify
  start/end/duration/project/note/status/source, does not delete
  assignment / resource / session-note rows, hides the activity from the
  default Timeline);
- successful soft delete (sets ``is_deleted = 1``, does not physically
  delete the row, does not modify start/end/duration/project/note/status/
  source, does not delete assignment / resource / session-note rows,
  removes the activity from the default Timeline);
- session-level hide / soft delete on a single-activity session succeed;
- session-level hide / soft delete on a multi-activity session raise
  ``multi_activity_hide`` / ``multi_activity_delete``;
- service UPDATE rowcount 0 maps to ``operation_failed``;
- validation failure leaves the original activity completely unchanged.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineVisibilityError
from worktrace.db import get_connection
from worktrace.services import activity_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]




def _seed_closed_activity(start="09:00:00", end="09:30:00", day="2026-06-25"):
    """Seed a single closed activity and return its id."""
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "A1.docx",
        start_time=f"{day} {start}",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} {end}")
    return aid


def _seed_two_closed_activities(
    start1="09:00:00",
    end1="09:30:00",
    start2="09:30:00",
    end2="10:00:00",
    day="2026-06-25",
):
    """Seed two closed activities and return their ids."""
    a1 = _seed_closed_activity(start=start1, end=end1, day=day)
    a2 = _seed_closed_activity(start=start2, end=end2, day=day)
    return [a1, a2]


def _count_activities() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()
    return int(row["c"])


def _count_assignments(activity_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_project_assignment "
            "WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return int(row["c"])


def _count_resources(activity_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return int(row["c"])


def _get_session_note(report_date: str, first_activity_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT note FROM project_session_note "
            "WHERE report_date = ? AND first_activity_id = ?",
            (report_date, first_activity_id),
        ).fetchone()
    return row["note"] if row else None




def test_hide_activity_bool_id(temp_db):
    """``bool`` is a subclass of ``int``; it must be rejected."""
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_activity(True)
    assert exc.value.code == "invalid_id"


def test_hide_activity_non_int_id(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_activity("not an int")
    assert exc.value.code == "invalid_id"


def test_hide_activity_non_positive_id(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_activity(0)
    assert exc.value.code == "invalid_id"
    with pytest.raises(TimelineVisibilityError) as exc2:
        timeline_api.hide_timeline_activity(-1)
    assert exc2.value.code == "invalid_id"


def test_hide_activity_nonexistent_id(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_activity(999999)
    assert exc.value.code == "invalid_id"


def test_hide_activity_deleted_activity(temp_db):
    """A soft-deleted activity cannot be hidden (treated as missing)."""
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_activity(aid)
    assert exc.value.code == "invalid_id"


def test_hide_activity_in_progress(temp_db):
    """An in-progress activity (raw ``end_time IS NULL``) cannot be hidden."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    # aid is still open (end_time IS NULL)
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_activity(aid)
    assert exc.value.code == "in_progress"




def test_soft_delete_activity_bool_id(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_activity(True)
    assert exc.value.code == "invalid_id"


def test_soft_delete_activity_non_int_id(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_activity("not an int")
    assert exc.value.code == "invalid_id"


def test_soft_delete_activity_non_positive_id(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_activity(0)
    assert exc.value.code == "invalid_id"


def test_soft_delete_activity_nonexistent_id(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_activity(999999)
    assert exc.value.code == "invalid_id"


def test_soft_delete_activity_deleted_activity(temp_db):
    """Soft delete is NOT idempotent: deleting an already-deleted activity
    fails with ``invalid_id``."""
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_activity(aid)
    assert exc.value.code == "invalid_id"


def test_soft_delete_activity_in_progress(temp_db):
    """An in-progress activity cannot be soft-deleted."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_activity(aid)
    assert exc.value.code == "in_progress"




def test_hide_activity_success_sets_is_hidden(temp_db):
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1
    # is_deleted must remain 0.
    assert int(activity.get("is_deleted") or 0) == 0


def test_hide_activity_idempotent(temp_db):
    """Hiding an already-hidden activity succeeds (the UPDATE still matches
    the row because ``is_deleted = 0`` and ``end_time IS NOT NULL``)."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    # Second hide must not raise.
    timeline_api.hide_timeline_activity(aid)
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1


def test_hide_activity_does_not_modify_core_fields(temp_db):
    """Hide must not touch start/end/duration/project/note/status/source."""
    aid = _seed_closed_activity()
    before = activity_service.get_activity(aid)
    timeline_api.hide_timeline_activity(aid)
    after = activity_service.get_activity(aid)
    assert after["start_time"] == before["start_time"]
    assert after["end_time"] == before["end_time"]
    assert int(after["duration_seconds"] or 0) == int(before["duration_seconds"] or 0)
    assert after["project_id"] == before["project_id"]
    assert after["note"] == before["note"]
    assert after["status"] == before["status"]
    assert after["source"] == before["source"]


def test_hide_activity_preserves_assignments(temp_db):
    """Hide must not delete activity_project_assignment rows."""
    aid = _seed_closed_activity()
    before = _count_assignments(aid)
    assert before >= 1
    timeline_api.hide_timeline_activity(aid)
    after = _count_assignments(aid)
    assert after == before


def test_hide_activity_preserves_resources(temp_db):
    """Hide must not delete activity_resource rows."""
    aid = _seed_closed_activity()
    before = _count_resources(aid)
    assert before >= 1
    timeline_api.hide_timeline_activity(aid)
    after = _count_resources(aid)
    assert after == before


def test_hide_activity_preserves_session_note(temp_db):
    """Hide must not delete project_session_note rows."""
    aid = _seed_closed_activity()
    timeline_api.update_timeline_session_note("2026-06-25", aid, "session note")
    assert _get_session_note("2026-06-25", aid) == "session note"
    timeline_api.hide_timeline_activity(aid)
    # The session note row must still exist with the same content.
    assert _get_session_note("2026-06-25", aid) == "session note"


def test_hide_activity_removes_from_default_timeline(temp_db):
    """A hidden activity must not appear in the default Timeline
    (``include_hidden=False``)."""
    aid = _seed_closed_activity()
    sessions_before = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    assert any(aid in (s.get("activity_ids") or []) for s in sessions_before)
    timeline_api.hide_timeline_activity(aid)
    sessions_after = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    assert not any(aid in (s.get("activity_ids") or []) for s in sessions_after)


def test_hide_activity_visible_with_include_hidden(temp_db):
    """A hidden activity still appears when ``include_hidden=True``."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=True, ensure_context=True
    )
    assert any(aid in (s.get("activity_ids") or []) for s in sessions)




def test_soft_delete_activity_success_sets_is_deleted(temp_db):
    aid = _seed_closed_activity()
    timeline_api.soft_delete_timeline_activity(aid)
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_deleted") or 0) == 1
    # is_hidden must remain unchanged (soft delete does not hide).
    assert int(activity.get("is_hidden") or 0) == 0


def test_soft_delete_activity_does_not_physically_delete(temp_db):
    """The DB row must still exist after a soft delete."""
    aid = _seed_closed_activity()
    before_count = _count_activities()
    timeline_api.soft_delete_timeline_activity(aid)
    after_count = _count_activities()
    assert after_count == before_count
    # The row is still retrievable.
    assert activity_service.get_activity(aid) is not None


def test_soft_delete_activity_does_not_modify_core_fields(temp_db):
    """Soft delete must not touch start/end/duration/project/note/status/source."""
    aid = _seed_closed_activity()
    before = activity_service.get_activity(aid)
    timeline_api.soft_delete_timeline_activity(aid)
    after = activity_service.get_activity(aid)
    assert after["start_time"] == before["start_time"]
    assert after["end_time"] == before["end_time"]
    assert int(after["duration_seconds"] or 0) == int(before["duration_seconds"] or 0)
    assert after["project_id"] == before["project_id"]
    assert after["note"] == before["note"]
    assert after["status"] == before["status"]
    assert after["source"] == before["source"]


def test_soft_delete_activity_preserves_assignments(temp_db):
    """Soft delete must not delete activity_project_assignment rows."""
    aid = _seed_closed_activity()
    before = _count_assignments(aid)
    assert before >= 1
    timeline_api.soft_delete_timeline_activity(aid)
    after = _count_assignments(aid)
    assert after == before


def test_soft_delete_activity_preserves_resources(temp_db):
    """Soft delete must not delete activity_resource rows."""
    aid = _seed_closed_activity()
    before = _count_resources(aid)
    assert before >= 1
    timeline_api.soft_delete_timeline_activity(aid)
    after = _count_resources(aid)
    assert after == before


def test_soft_delete_activity_preserves_session_note(temp_db):
    """Soft delete must not delete project_session_note rows."""
    aid = _seed_closed_activity()
    timeline_api.update_timeline_session_note("2026-06-25", aid, "session note")
    assert _get_session_note("2026-06-25", aid) == "session note"
    timeline_api.soft_delete_timeline_activity(aid)
    # The session note row must still exist with the same content.
    assert _get_session_note("2026-06-25", aid) == "session note"


def test_soft_delete_activity_removes_from_default_timeline(temp_db):
    """A soft-deleted activity must not appear in the default Timeline."""
    aid = _seed_closed_activity()
    sessions_before = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    assert any(aid in (s.get("activity_ids") or []) for s in sessions_before)
    timeline_api.soft_delete_timeline_activity(aid)
    sessions_after = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    assert not any(aid in (s.get("activity_ids") or []) for s in sessions_after)




def test_hide_session_single_activity_success(temp_db):
    """A single-activity session hide is equivalent to hiding that activity."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_session([aid])
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1


def test_soft_delete_session_single_activity_success(temp_db):
    """A single-activity session soft delete is equivalent to soft-deleting
    that activity."""
    aid = _seed_closed_activity()
    timeline_api.soft_delete_timeline_session([aid])
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_deleted") or 0) == 1


def test_hide_session_multi_activity_rejected(temp_db):
    """A multi-activity session hide must raise ``multi_activity_hide``."""
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session(ids)
    assert exc.value.code == "multi_activity_hide"


def test_soft_delete_session_multi_activity_rejected(temp_db):
    """A multi-activity session soft delete must raise
    ``multi_activity_delete``."""
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_session(ids)
    assert exc.value.code == "multi_activity_delete"


def test_hide_session_dedup_single_activity(temp_db):
    """Duplicate ids in a session list are deduplicated; if exactly one id
    remains after dedup, the hide succeeds."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_session([aid, aid])
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1


def test_hide_session_in_progress_rejected(temp_db):
    """An in-progress activity in a session-level hide raises
    ``in_progress``."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session([aid])
    assert exc.value.code == "in_progress"


def test_soft_delete_session_in_progress_rejected(temp_db):
    """An in-progress activity in a session-level soft delete raises
    ``in_progress``."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_session([aid])
    assert exc.value.code == "in_progress"




def test_hide_session_non_list(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session("not a list")
    assert exc.value.code == "invalid_id"


def test_hide_session_bool(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session(True)
    assert exc.value.code == "invalid_id"


def test_hide_session_empty_list(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session([])
    assert exc.value.code == "invalid_id"


def test_hide_session_bool_id_in_list(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session([aid, True])
    assert exc.value.code == "invalid_id"


def test_hide_session_non_positive_id(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session([aid, 0])
    assert exc.value.code == "invalid_id"


def test_hide_session_nonexistent_id(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session([aid, 999999])
    assert exc.value.code == "invalid_id"


def test_hide_session_deleted_id(temp_db):
    """A deleted activity id in the session list raises ``invalid_id``."""
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.hide_timeline_session([aid])
    assert exc.value.code == "invalid_id"


def test_soft_delete_session_non_list(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_session("not a list")
    assert exc.value.code == "invalid_id"


def test_soft_delete_session_empty_list(temp_db):
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_session([])
    assert exc.value.code == "invalid_id"


def test_soft_delete_session_bool_id_in_list(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineVisibilityError) as exc:
        timeline_api.soft_delete_timeline_session([aid, True])
    assert exc.value.code == "invalid_id"




def test_hide_activity_race_condition_operation_failed(temp_db):
    """If the service-layer ``hide_activity`` raises ``ValueError`` (race
    condition: the activity was deleted or re-opened between validation and
    write), the API must map it to ``operation_failed``."""
    aid = _seed_closed_activity()
    with patch.object(activity_service, "hide_activity", side_effect=ValueError("race")):
        with pytest.raises(TimelineVisibilityError) as exc:
            timeline_api.hide_timeline_activity(aid)
    assert exc.value.code == "operation_failed"


def test_soft_delete_activity_race_condition_operation_failed(temp_db):
    """If the service-layer ``soft_delete_activity`` raises ``ValueError``
    (race condition), the API must map it to ``operation_failed``."""
    aid = _seed_closed_activity()
    with patch.object(
        activity_service, "soft_delete_activity", side_effect=ValueError("race")
    ):
        with pytest.raises(TimelineVisibilityError) as exc:
            timeline_api.soft_delete_timeline_activity(aid)
    assert exc.value.code == "operation_failed"


def test_hide_session_race_condition_operation_failed(temp_db):
    """A race condition during a session-level hide maps to
    ``operation_failed``."""
    aid = _seed_closed_activity()
    with patch.object(activity_service, "hide_activity", side_effect=ValueError("race")):
        with pytest.raises(TimelineVisibilityError) as exc:
            timeline_api.hide_timeline_session([aid])
    assert exc.value.code == "operation_failed"


def test_soft_delete_session_race_condition_operation_failed(temp_db):
    """A race condition during a session-level soft delete maps to
    ``operation_failed``."""
    aid = _seed_closed_activity()
    with patch.object(
        activity_service, "soft_delete_activity", side_effect=ValueError("race")
    ):
        with pytest.raises(TimelineVisibilityError) as exc:
            timeline_api.soft_delete_timeline_session([aid])
    assert exc.value.code == "operation_failed"




def test_hide_activity_validation_failure_leaves_activity_unchanged(temp_db):
    """If validation fails, the activity must be completely unchanged."""
    aid = _seed_closed_activity()
    before = activity_service.get_activity(aid)
    before_count = _count_activities()
    with pytest.raises(TimelineVisibilityError):
        timeline_api.hide_timeline_activity(0)
    after = activity_service.get_activity(aid)
    assert after == before
    assert _count_activities() == before_count


def test_soft_delete_activity_validation_failure_leaves_activity_unchanged(temp_db):
    """If validation fails, the activity must be completely unchanged."""
    aid = _seed_closed_activity()
    before = activity_service.get_activity(aid)
    before_count = _count_activities()
    with pytest.raises(TimelineVisibilityError):
        timeline_api.soft_delete_timeline_activity(0)
    after = activity_service.get_activity(aid)
    assert after == before
    assert _count_activities() == before_count


def test_hide_session_validation_failure_leaves_activities_unchanged(temp_db):
    """If session-level validation fails (multi-activity), neither activity
    is hidden."""
    ids = _seed_two_closed_activities()
    before = {aid: activity_service.get_activity(aid) for aid in ids}
    with pytest.raises(TimelineVisibilityError):
        timeline_api.hide_timeline_session(ids)
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert int(after.get("is_hidden") or 0) == 0
        assert after["start_time"] == before[aid]["start_time"]
        assert after["end_time"] == before[aid]["end_time"]


def test_soft_delete_session_validation_failure_leaves_activities_unchanged(temp_db):
    """If session-level validation fails (multi-activity), neither activity
    is soft-deleted."""
    ids = _seed_two_closed_activities()
    before = {aid: activity_service.get_activity(aid) for aid in ids}
    with pytest.raises(TimelineVisibilityError):
        timeline_api.soft_delete_timeline_session(ids)
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert int(after.get("is_deleted") or 0) == 0
        assert after["start_time"] == before[aid]["start_time"]
        assert after["end_time"] == before[aid]["end_time"]




def test_service_hide_activity_zero_rowcount_raises(temp_db):
    """``hide_activity`` on a nonexistent id raises ``ValueError`` (rowcount
    0)."""
    with pytest.raises(ValueError):
        activity_service.hide_activity(999999)


def test_service_soft_delete_activity_zero_rowcount_raises(temp_db):
    """``soft_delete_activity`` on a nonexistent id raises ``ValueError``
    (rowcount 0)."""
    with pytest.raises(ValueError):
        activity_service.soft_delete_activity(999999)


def test_service_hide_activity_deleted_activity_zero_rowcount(temp_db):
    """``hide_activity`` on an already-deleted activity raises ``ValueError``
    (the WHERE clause excludes ``is_deleted = 1``)."""
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(ValueError):
        activity_service.hide_activity(aid)


def test_service_hide_activity_in_progress_zero_rowcount(temp_db):
    """``hide_activity`` on an in-progress activity raises ``ValueError``
    (the WHERE clause excludes ``end_time IS NULL``)."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(ValueError):
        activity_service.hide_activity(aid)


# ``soft_delete_activity`` write paths to confirm the hardening invariants


def test_service_hide_activity_idempotent(temp_db):
    """``hide_activity`` is idempotent at the service layer: calling it
    twice on the same closed activity succeeds both times. The WHERE
    clause only excludes ``is_deleted = 1`` and ``end_time IS NULL``, so
    an already-hidden row still matches and the second UPDATE succeeds."""
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    # Second hide at the service layer must NOT raise.
    activity_service.hide_activity(aid)
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1
    assert int(activity.get("is_deleted") or 0) == 0


def test_service_soft_delete_activity_non_idempotent(temp_db):
    """``soft_delete_activity`` is NOT idempotent at the service layer: the
    second call on an already-deleted activity raises ``ValueError``
    because the WHERE clause excludes ``is_deleted = 1``."""
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(ValueError):
        activity_service.soft_delete_activity(aid)
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_deleted") or 0) == 1


def test_service_soft_delete_activity_in_progress_zero_rowcount(temp_db):
    """``soft_delete_activity`` on an in-progress activity raises
    ``ValueError`` (the WHERE clause excludes ``end_time IS NULL``)."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(ValueError):
        activity_service.soft_delete_activity(aid)


def test_service_hide_activity_does_not_modify_core_fields(temp_db):
    """``hide_activity`` must not touch start/end/duration/project/note/
    status/source at the service layer."""
    aid = _seed_closed_activity()
    before = activity_service.get_activity(aid)
    activity_service.hide_activity(aid)
    after = activity_service.get_activity(aid)
    assert after["start_time"] == before["start_time"]
    assert after["end_time"] == before["end_time"]
    assert int(after["duration_seconds"] or 0) == int(before["duration_seconds"] or 0)
    assert after["project_id"] == before["project_id"]
    assert after["note"] == before["note"]
    assert after["status"] == before["status"]
    assert after["source"] == before["source"]
    # is_deleted must remain unchanged.
    assert int(after.get("is_deleted") or 0) == 0


def test_service_soft_delete_activity_does_not_modify_core_fields(temp_db):
    """``soft_delete_activity`` must not touch start/end/duration/project/
    note/status/source at the service layer."""
    aid = _seed_closed_activity()
    before = activity_service.get_activity(aid)
    activity_service.soft_delete_activity(aid)
    after = activity_service.get_activity(aid)
    assert after["start_time"] == before["start_time"]
    assert after["end_time"] == before["end_time"]
    assert int(after["duration_seconds"] or 0) == int(before["duration_seconds"] or 0)
    assert after["project_id"] == before["project_id"]
    assert after["note"] == before["note"]
    assert after["status"] == before["status"]
    assert after["source"] == before["source"]
    # is_hidden must remain unchanged.
    assert int(after.get("is_hidden") or 0) == 0


def test_service_hide_activity_preserves_assignments(temp_db):
    """``hide_activity`` must not delete activity_project_assignment rows."""
    aid = _seed_closed_activity()
    before = _count_assignments(aid)
    assert before >= 1
    activity_service.hide_activity(aid)
    after = _count_assignments(aid)
    assert after == before


def test_service_soft_delete_activity_preserves_assignments(temp_db):
    """``soft_delete_activity`` must not delete activity_project_assignment
    rows."""
    aid = _seed_closed_activity()
    before = _count_assignments(aid)
    assert before >= 1
    activity_service.soft_delete_activity(aid)
    after = _count_assignments(aid)
    assert after == before


def test_service_hide_activity_preserves_resources(temp_db):
    """``hide_activity`` must not delete activity_resource rows."""
    aid = _seed_closed_activity()
    before = _count_resources(aid)
    assert before >= 1
    activity_service.hide_activity(aid)
    after = _count_resources(aid)
    assert after == before


def test_service_soft_delete_activity_preserves_resources(temp_db):
    """``soft_delete_activity`` must not delete activity_resource rows."""
    aid = _seed_closed_activity()
    before = _count_resources(aid)
    assert before >= 1
    activity_service.soft_delete_activity(aid)
    after = _count_resources(aid)
    assert after == before


def test_service_hide_activity_does_not_physically_delete(temp_db):
    """``hide_activity`` must not remove the row from ``activity_log``."""
    aid = _seed_closed_activity()
    before_count = _count_activities()
    activity_service.hide_activity(aid)
    after_count = _count_activities()
    assert after_count == before_count
    assert activity_service.get_activity(aid) is not None


def test_service_soft_delete_activity_does_not_physically_delete(temp_db):
    """``soft_delete_activity`` must not remove the row from
    ``activity_log``."""
    aid = _seed_closed_activity()
    before_count = _count_activities()
    activity_service.soft_delete_activity(aid)
    after_count = _count_activities()
    assert after_count == before_count
    # The row is still retrievable by direct id lookup (the service's
    # ``get_activity`` does not filter on ``is_deleted``).
    assert activity_service.get_activity(aid) is not None


def test_service_hide_activity_does_not_modify_is_deleted(temp_db):
    """``hide_activity`` must leave ``is_deleted`` at 0."""
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_deleted") or 0) == 0
    assert int(activity.get("is_hidden") or 0) == 1


def test_service_soft_delete_activity_does_not_modify_is_hidden(temp_db):
    """``soft_delete_activity`` must leave ``is_hidden`` unchanged (if the
    activity is already hidden, ``is_hidden`` stays 1)."""
    aid = _seed_closed_activity()
    # Hide first, then soft delete. ``is_hidden`` must remain 1.
    activity_service.hide_activity(aid)
    activity_service.soft_delete_activity(aid)
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1
    assert int(activity.get("is_deleted") or 0) == 1
