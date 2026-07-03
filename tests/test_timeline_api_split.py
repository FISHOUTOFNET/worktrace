"""Tests for the Timeline activity-split API and service layer.

Covers ``worktrace.api.timeline_api.split_timeline_activity`` and
``worktrace.api.timeline_api.split_timeline_session``, and the underlying
``worktrace.services.activity_service.split_activity`` write:

- input validation (non-positive id, bool id, nonexistent id, deleted
  activity, in-progress activity, non-string split_time, bad time format,
  T separator, timezone suffix, missing seconds, split_time <= start,
  split_time >= end);
- successful splits (single-activity split, duration recomputation on both
  halves, duration sum equals original, project assignment inheritance,
  manual assignment inheritance, resource association inheritance, session
  note not auto-copied to the new back half);
- cross-day activity split producing reasonable report_date slices;
- no partial writes on validation failure (original activity unchanged, no
  new activity created);
- session-level split: single-activity success, multi-activity rejection;
- race-condition handling (UPDATE affecting 0 rows rolls back the whole
  operation).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineSplitError
from worktrace.db import get_connection
from worktrace.services import activity_service




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


def _seed_session():
    """Seed a simple two-activity session on 2026-06-25."""
    a1 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(a1)
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A2.docx", start_time="2026-06-25 09:10:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, "2026-06-25 09:30:00")
    return [a1, a2]


def _count_activities() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()
    return int(row["c"])


def _get_assignment(activity_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT project_id, confidence, source, is_manual "
            "FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return dict(row) if row else None


def _get_resource(activity_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT resource_kind, display_name, identity_key, path_hint "
            "FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return dict(row) if row else None




def test_split_activity_non_positive_id(temp_db):
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(0, "2026-06-25 09:15:00")
    assert exc.value.code == "invalid_id"
    with pytest.raises(TimelineSplitError) as exc2:
        timeline_api.split_timeline_activity(-1, "2026-06-25 09:15:00")
    assert exc2.value.code == "invalid_id"


def test_split_activity_bool_id(temp_db):
    """``bool`` is a subclass of ``int``; it must be rejected so ``True``
    does not silently coerce to ``1``."""
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(True, "2026-06-25 09:15:00")
    assert exc.value.code == "invalid_id"
    with pytest.raises(TimelineSplitError) as exc2:
        timeline_api.split_timeline_activity(False, "2026-06-25 09:15:00")
    assert exc2.value.code == "invalid_id"


def test_split_activity_nonexistent_id(temp_db):
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(999999, "2026-06-25 09:15:00")
    assert exc.value.code == "invalid_id"


def test_split_activity_deleted_activity(temp_db):
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert exc.value.code == "invalid_id"


def test_split_activity_in_progress(temp_db):
    """An open activity (``end_time IS NULL``) cannot be split."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert exc.value.code == "in_progress"


def test_split_activity_non_string_split_time(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(aid, 12345)
    assert exc.value.code == "invalid_time"
    with pytest.raises(TimelineSplitError) as exc2:
        timeline_api.split_timeline_activity(aid, None)
    assert exc2.value.code == "invalid_time"


def test_split_activity_missing_seconds(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:15")
    assert exc.value.code == "invalid_time"


def test_split_activity_t_separator_rejected(temp_db):
    """The ISO ``T`` separator must be rejected; only
    ``YYYY-MM-DD HH:MM:SS`` (space separator) is accepted."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(aid, "2026-06-25T09:15:00")
    assert exc.value.code == "invalid_time"


def test_split_activity_timezone_suffix_rejected(temp_db):
    """Timezone suffixes must be rejected; only naive
    ``YYYY-MM-DD HH:MM:SS`` is accepted."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00+08:00")
    assert exc.value.code == "invalid_time"
    with pytest.raises(TimelineSplitError) as exc2:
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00Z")
    assert exc2.value.code == "invalid_time"


def test_split_activity_split_le_start(temp_db):
    """``split_time <= start_time`` must be rejected (zero first half)."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:00:00")
    assert exc.value.code == "outside_range"
    with pytest.raises(TimelineSplitError) as exc2:
        timeline_api.split_timeline_activity(aid, "2026-06-25 08:00:00")
    assert exc2.value.code == "outside_range"


def test_split_activity_split_ge_end(temp_db):
    """``split_time >= end_time`` must be rejected (zero second half)."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:30:00")
    assert exc.value.code == "outside_range"
    with pytest.raises(TimelineSplitError) as exc2:
        timeline_api.split_timeline_activity(aid, "2026-06-25 10:00:00")
    assert exc2.value.code == "outside_range"




def test_split_activity_success(temp_db):
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert result["original_activity_id"] == aid
    assert isinstance(result["new_activity_id"], int)
    assert result["new_activity_id"] != aid
    # Original activity is now the front half: start unchanged, end = split
    original = activity_service.get_activity(aid)
    assert original["start_time"] == "2026-06-25 09:00:00"
    assert original["end_time"] == "2026-06-25 09:15:00"
    # New activity is the back half: start = split, end = original end
    new_act = activity_service.get_activity(result["new_activity_id"])
    assert new_act["start_time"] == "2026-06-25 09:15:00"
    assert new_act["end_time"] == "2026-06-25 09:30:00"


def test_split_activity_duration_precisely_recomputed(temp_db):
    """Both halves' ``duration_seconds`` must exactly equal the second
    difference of their new ranges."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    # Original duration: 30 min = 1800 seconds
    before = activity_service.get_activity(aid)
    assert int(before["duration_seconds"]) == 1800
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    # Front half: 09:00-09:15 = 900 seconds
    front = activity_service.get_activity(aid)
    assert int(front["duration_seconds"]) == 900
    # Back half: 09:15-09:30 = 900 seconds
    back = activity_service.get_activity(result["new_activity_id"])
    assert int(back["duration_seconds"]) == 900


def test_split_activity_duration_sum_equals_original(temp_db):
    """The sum of the two halves' durations must equal the original
    duration."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    before = activity_service.get_activity(aid)
    orig_duration = int(before["duration_seconds"])
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:10:00")
    front = activity_service.get_activity(aid)
    back = activity_service.get_activity(result["new_activity_id"])
    assert int(front["duration_seconds"]) + int(back["duration_seconds"]) == orig_duration


def test_split_activity_original_id_unchanged(temp_db):
    """The original activity id must be preserved (only its end_time is
    updated). The new activity gets a new, different id."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    before_count = _count_activities()
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    # The original id is still a valid activity with the front half.
    original = activity_service.get_activity(aid)
    assert original is not None
    assert original["id"] == aid
    # One new activity was created.
    assert _count_activities() == before_count + 1
    assert result["new_activity_id"] > aid


def test_split_activity_project_assignment_inherited(temp_db):
    """The new activity must inherit the original activity's project
    assignment so it does not become "未归类"."""
    from worktrace.services import project_service

    project = project_service.create_project("TestProj")
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A.docx",
        start_time="2026-06-25 09:00:00",
        project_id=project,
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-25 09:30:00")
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    front_assignment = _get_assignment(aid)
    back_assignment = _get_assignment(result["new_activity_id"])
    assert front_assignment is not None
    assert back_assignment is not None
    assert int(back_assignment["project_id"]) == project
    assert int(back_assignment["project_id"]) == int(front_assignment["project_id"])


def test_split_activity_manual_assignment_inherited(temp_db):
    """A manual project assignment on the original activity must be copied
    to the new activity (``is_manual=1`` preserved)."""
    from worktrace.services import project_service

    project = project_service.create_project("ManualProj")
    aid = _seed_closed_activity()
    # Apply a manual assignment to the original activity.
    activity_service.update_activity_project(aid, project, manual=True)
    orig_assignment = _get_assignment(aid)
    assert int(orig_assignment["is_manual"]) == 1
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    back_assignment = _get_assignment(result["new_activity_id"])
    assert back_assignment is not None
    assert int(back_assignment["project_id"]) == project
    assert int(back_assignment["is_manual"]) == 1
    assert back_assignment["source"] == orig_assignment["source"]


def test_split_activity_resource_inherited(temp_db):
    """The new activity must inherit the original activity's resource row
    so the resource display name is preserved on both halves."""
    aid = _seed_closed_activity()
    orig_resource = _get_resource(aid)
    assert orig_resource is not None
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    back_resource = _get_resource(result["new_activity_id"])
    assert back_resource is not None
    assert back_resource["resource_kind"] == orig_resource["resource_kind"]
    assert back_resource["display_name"] == orig_resource["display_name"]
    assert back_resource["identity_key"] == orig_resource["identity_key"]


def test_split_activity_note_not_copied_to_new_activity(temp_db):
    """The ``activity_log.note`` column must NOT be copied to the new
    activity. The primary note mechanism is ``project_session_note``
    keyed by ``(report_date, first_activity_id)``; the front half keeps
    the original id and thus keeps any session note. The back half
    starts without an activity note."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A.docx",
        start_time="2026-06-25 09:00:00",
        note="activity-level note",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-25 09:30:00")
    # Sanity check: the original activity has the note.
    before = activity_service.get_activity(aid)
    assert before.get("note") == "activity-level note"
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    # The original (front half) keeps the note.
    front = activity_service.get_activity(aid)
    assert front.get("note") == "activity-level note"
    # The new (back half) does NOT copy the activity note.
    back = activity_service.get_activity(result["new_activity_id"])
    assert back.get("note") is None or back.get("note") == ""


def test_split_activity_session_note_not_copied_to_new_half(temp_db):
    """``project_session_note`` keyed by ``(report_date, first_activity_id)``
    must NOT be auto-copied to the new back half. The front half keeps the
    original activity id and thus keeps the session note; the back half
    does not get a session note automatically."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    # Write a session note keyed to the original activity id.
    timeline_api.update_timeline_session_note("2026-06-25", aid, "session note")
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    # The session note keyed to the original (front) activity id still exists.
    with get_connection() as conn:
        front_row = conn.execute(
            "SELECT note FROM project_session_note "
            "WHERE report_date = ? AND first_activity_id = ?",
            ("2026-06-25", aid),
        ).fetchone()
    assert front_row is not None
    assert front_row["note"] == "session note"
    # No session note was auto-created for the new back-half activity id.
    with get_connection() as conn:
        back_row = conn.execute(
            "SELECT note FROM project_session_note "
            "WHERE report_date = ? AND first_activity_id = ?",
            ("2026-06-25", result["new_activity_id"]),
        ).fetchone()
    assert back_row is None




def test_split_activity_cross_day_split_report_date_slices(temp_db):
    """A cross-day activity split must produce reasonable report_date
    slices when read back through timeline_service."""
    # Seed a cross-day activity: 2026-06-25 23:00 -> 2026-06-26 01:00 (2h)
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A.docx",
        start_time="2026-06-25 23:00:00",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-26 01:00:00")
    # Split at midnight: front = 23:00-24:00 (on 06-25), back = 00:00-01:00
    # (on 06-26). The split_time is strictly inside the activity range.
    result = timeline_api.split_timeline_activity(aid, "2026-06-26 00:00:00")
    front = activity_service.get_activity(aid)
    back = activity_service.get_activity(result["new_activity_id"])
    assert front["start_time"] == "2026-06-25 23:00:00"
    assert front["end_time"] == "2026-06-26 00:00:00"
    assert back["start_time"] == "2026-06-26 00:00:00"
    assert back["end_time"] == "2026-06-26 01:00:00"
    # Each half should now appear on only its respective report_date.
    sessions_day1 = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    sessions_day2 = timeline_api.get_project_sessions_by_date(
        "2026-06-26", include_hidden=False, ensure_context=True
    )
    day1_has_front = any(aid in (s.get("activity_ids") or []) for s in sessions_day1)
    day2_has_back = any(
        result["new_activity_id"] in (s.get("activity_ids") or [])
        for s in sessions_day2
    )
    assert day1_has_front, "front half must appear on 2026-06-25"
    assert day2_has_back, "back half must appear on 2026-06-26"




def test_split_activity_no_partial_write_on_validation_failure(temp_db):
    """If validation fails, the original activity must be untouched and no
    new activity must be created."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    original = activity_service.get_activity(aid)
    orig_start = original["start_time"]
    orig_end = original["end_time"]
    orig_duration = int(original["duration_seconds"])
    before_count = _count_activities()
    with pytest.raises(TimelineSplitError):
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:30:00")
    after = activity_service.get_activity(aid)
    assert after["start_time"] == orig_start
    assert after["end_time"] == orig_end
    assert int(after["duration_seconds"]) == orig_duration
    assert _count_activities() == before_count


def test_split_activity_no_partial_write_on_bad_format(temp_db):
    """A bad split_time format must not create a new activity."""
    aid = _seed_closed_activity()
    before_count = _count_activities()
    with pytest.raises(TimelineSplitError):
        timeline_api.split_timeline_activity(aid, "not-a-time")
    assert _count_activities() == before_count


def test_split_activity_no_partial_write_on_in_progress(temp_db):
    """An in-progress activity rejection must not create a new activity."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    before_count = _count_activities()
    with pytest.raises(TimelineSplitError):
        timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert _count_activities() == before_count




def test_split_session_single_activity_success(temp_db):
    """A single-activity session-level split must succeed and produce the
    same result as ``split_timeline_activity`` on that activity."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    result = timeline_api.split_timeline_session([aid], "2026-06-25 09:15:00")
    assert result["original_activity_id"] == aid
    assert isinstance(result["new_activity_id"], int)
    front = activity_service.get_activity(aid)
    back = activity_service.get_activity(result["new_activity_id"])
    assert front["end_time"] == "2026-06-25 09:15:00"
    assert back["start_time"] == "2026-06-25 09:15:00"
    assert back["end_time"] == "2026-06-25 09:30:00"


def test_split_session_multi_activity_rejected(temp_db):
    """A multi-activity session must raise ``multi_activity``."""
    ids = _seed_session()
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_session(ids, "2026-06-25 09:15:00")
    assert exc.value.code == "multi_activity"


def test_split_session_multi_activity_no_partial_write(temp_db):
    """If a multi-activity session is rejected, no activity in the session
    must be modified and no new activity must be created."""
    ids = _seed_session()
    originals = {aid: activity_service.get_activity(aid) for aid in ids}
    before_count = _count_activities()
    with pytest.raises(TimelineSplitError):
        timeline_api.split_timeline_session(ids, "2026-06-25 09:15:00")
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert after["start_time"] == originals[aid]["start_time"]
        assert after["end_time"] == originals[aid]["end_time"]
    assert _count_activities() == before_count


def test_split_session_dedup_single_activity(temp_db):
    """Duplicate ids that resolve to one activity should succeed."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    result = timeline_api.split_timeline_session([aid, aid], "2026-06-25 09:15:00")
    assert result["original_activity_id"] == aid
    assert isinstance(result["new_activity_id"], int)


def test_split_session_empty_list(temp_db):
    with pytest.raises(ValueError):
        timeline_api.split_timeline_session([], "2026-06-25 09:15:00")


def test_split_session_in_progress(temp_db):
    """A single-activity session that is still open must raise
    ``in_progress``."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_session([aid], "2026-06-25 09:15:00")
    assert exc.value.code == "in_progress"


def test_split_session_bad_time_format(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_session([aid], "bad")
    assert exc.value.code == "invalid_time"


def test_split_session_split_outside_range(temp_db):
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    with pytest.raises(TimelineSplitError) as exc:
        timeline_api.split_timeline_session([aid], "2026-06-25 09:30:00")
    assert exc.value.code == "outside_range"




def test_split_activity_race_condition_returns_operation_failed(temp_db):
    """If the activity is deleted between API validation and the service
    write (race condition), the API must raise
    ``TimelineSplitError("operation_failed")`` instead of silently
    succeeding or surfacing internal details."""
    aid = _seed_closed_activity()
    original_split = activity_service.split_activity

    def racing_split(activity_id, split_time):
        # Simulate the activity being deleted between validation and write.
        activity_service.soft_delete_activity(activity_id)
        return original_split(activity_id, split_time)

    with patch.object(
        activity_service, "split_activity", side_effect=racing_split
    ):
        with pytest.raises(TimelineSplitError) as exc:
            timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert exc.value.code == "operation_failed"


def test_split_session_race_condition_returns_operation_failed(temp_db):
    """Session-level split race condition must also raise
    ``operation_failed``."""
    aid = _seed_closed_activity()
    original_split = activity_service.split_activity

    def racing_split(activity_id, split_time):
        activity_service.soft_delete_activity(activity_id)
        return original_split(activity_id, split_time)

    with patch.object(
        activity_service, "split_activity", side_effect=racing_split
    ):
        with pytest.raises(TimelineSplitError) as exc:
            timeline_api.split_timeline_session([aid], "2026-06-25 09:15:00")
    assert exc.value.code == "operation_failed"




def test_service_split_activity_raises_on_deleted_activity(temp_db):
    """The service layer must raise ``ValueError`` when the activity is
    deleted (the SELECT guard catches it before any write)."""
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(ValueError):
        activity_service.split_activity(aid, "2026-06-25 09:15:00")


def test_service_split_activity_raises_on_in_progress_activity(temp_db):
    """The service layer must raise ``ValueError`` when the activity is
    still open (``end_time IS NULL``)."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(ValueError):
        activity_service.split_activity(aid, "2026-06-25 09:15:00")


def test_service_split_activity_raises_on_nonexistent_activity(temp_db):
    """The service layer must raise ``ValueError`` when the activity id
    does not exist."""
    with pytest.raises(ValueError):
        activity_service.split_activity(999999, "2026-06-25 09:15:00")


def test_service_split_activity_atomic_rollback_on_zero_row_update(temp_db):
    """If the UPDATE on the original activity affects 0 rows (race
    condition: activity deleted/reopened between SELECT and UPDATE), the
    service must raise ``ValueError`` and NOT insert a new activity.

    This exercises the ``cur.rowcount == 0`` defensive guard inside
    ``split_activity``. We wrap the real connection so the SELECT returns
    the real (valid) row, but the UPDATE returns a fake cursor whose
    ``rowcount`` reports 0 — simulating the row being deleted/reopened
    between the SELECT and the UPDATE within the same transaction.
    """
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    before_count = _count_activities()
    real_get_connection = activity_service.get_connection

    class _ZeroRowCursor:
        """Fake cursor that always reports ``rowcount = 0``. The real
        UPDATE is still executed on the wrapped connection so the
        transaction state is valid; only the reported rowcount is faked
        so the defensive guard in ``split_activity`` fires."""

        def __init__(self, real_cursor):
            self._real = real_cursor

        @property
        def rowcount(self):
            return 0

        def __getattr__(self, name):
            return getattr(self._real, name)

    class _ZeroRowUpdateConn:
        """Wraps a real connection. The UPDATE statement inside
        ``split_activity`` returns a ``_ZeroRowCursor`` so the guard fires.
        All other statements delegate to the real connection."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, params=()):
            stripped = " ".join(sql.split())
            if (
                "UPDATE activity_log" in stripped
                and "SET end_time =" in stripped
                and "duration_seconds =" in stripped
            ):
                # Run the real UPDATE (so the transaction state is valid),
                # then wrap the cursor so rowcount reports 0.
                cur = self._real.execute(sql, params)
                return _ZeroRowCursor(cur)
            return self._real.execute(sql, params)

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    def patched_get_connection():
        return _ZeroRowUpdateConn(real_get_connection())

    with patch.object(
        activity_service, "get_connection", side_effect=patched_get_connection
    ):
        with pytest.raises(ValueError):
            activity_service.split_activity(aid, "2026-06-25 09:15:00")
    # No new activity should have been inserted: the transaction rolled back
    # when the UPDATE reported 0 rows affected. The original activity's
    # end_time may have been modified, but ``__exit__`` rolls back on the
    # exception, so it's restored too. Key invariant: no NEW row is created.
    assert _count_activities() == before_count




def test_split_activity_no_assignment_does_not_create_assignment(temp_db):
    """If the original activity has no ``activity_project_assignment`` row,
    the split must NOT create an assignment for the new activity either.
    This prevents the new back-half from getting a spurious assignment row
    that the original did not have."""
    aid = _seed_closed_activity()
    # Remove any assignment row that create_activity may have created so we
    # can verify the split does not fabricate one.
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM activity_project_assignment WHERE activity_id = ?",
            (aid,),
        )
    assert _get_assignment(aid) is None
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    # The new activity must also have no assignment row.
    assert _get_assignment(result["new_activity_id"]) is None


def test_split_activity_auto_assignment_inherited(temp_db):
    """An automatic (non-manual) project assignment on the original activity
    must be copied to the new activity with ``is_manual=0`` preserved."""
    from worktrace.services import project_service

    project = project_service.create_project("AutoProj")
    aid = _seed_closed_activity()
    # Insert an auto (non-manual) assignment directly.
    from worktrace.db import now_str

    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual,
                suggested_project_name, created_at, updated_at
            )
            VALUES (?, ?, 60, 'keyword_rule', 0, NULL, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                project_id = excluded.project_id,
                confidence = excluded.confidence,
                source = excluded.source,
                is_manual = excluded.is_manual,
                updated_at = excluded.updated_at
            """,
            (aid, project, ts, ts),
        )
    orig = _get_assignment(aid)
    assert int(orig["is_manual"]) == 0
    assert orig["source"] == "keyword_rule"
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    back = _get_assignment(result["new_activity_id"])
    assert back is not None
    assert int(back["project_id"]) == project
    assert int(back["is_manual"]) == 0
    assert back["source"] == "keyword_rule"


def test_split_activity_created_at_not_copied(temp_db):
    """The new activity's ``created_at`` must reflect the write time (now),
    not the original activity's creation time. The original's ``created_at``
    must remain unchanged."""
    aid = _seed_closed_activity()
    before = activity_service.get_activity(aid)
    orig_created = before["created_at"]
    result = timeline_api.split_timeline_activity(aid, "2026-06-25 09:15:00")
    front = activity_service.get_activity(aid)
    back = activity_service.get_activity(result["new_activity_id"])
    # Original created_at is untouched.
    assert front["created_at"] == orig_created
    # New activity created_at is the write time (>= original created_at).
    assert back["created_at"] >= orig_created


def test_service_split_activity_lastrowid_guard(temp_db):
    """If the INSERT returns ``lastrowid <= 0`` (should not happen under
    normal sqlite3, but is a defensive guard), the service must raise
    ``ValueError`` and the transaction must roll back so the original
    activity is unchanged and no new activity is persisted."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    before_count = _count_activities()
    original = activity_service.get_activity(aid)
    orig_end = original["end_time"]
    orig_duration = int(original["duration_seconds"])
    real_get_connection = activity_service.get_connection

    class _ZeroLastrowidCursor:
        """Fake cursor whose ``lastrowid`` is always 0."""

        def __init__(self, real_cursor):
            self._real = real_cursor

        @property
        def lastrowid(self):
            return 0

        def __getattr__(self, name):
            return getattr(self._real, name)

    class _ZeroLastrowidConn:
        """Wraps a real connection. The INSERT into ``activity_log`` inside
        ``split_activity`` returns a ``_ZeroLastrowidCursor`` so the guard
        fires. All other statements delegate to the real connection."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, params=()):
            stripped = " ".join(sql.split())
            if "INSERT INTO activity_log" in stripped:
                cur = self._real.execute(sql, params)
                return _ZeroLastrowidCursor(cur)
            return self._real.execute(sql, params)

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    def patched_get_connection():
        return _ZeroLastrowidConn(real_get_connection())

    with patch.object(
        activity_service, "get_connection", side_effect=patched_get_connection
    ):
        with pytest.raises(ValueError):
            activity_service.split_activity(aid, "2026-06-25 09:15:00")
    # The transaction must have rolled back: no new activity, original
    # unchanged.
    assert _count_activities() == before_count
    after = activity_service.get_activity(aid)
    assert after["end_time"] == orig_end
    assert int(after["duration_seconds"]) == orig_duration


def test_service_split_activity_insert_failure_rolls_back(temp_db):
    """If the INSERT statement raises (e.g. a constraint error), the
    transaction must roll back so the original activity's end_time and
    duration_seconds are restored and no new activity is persisted."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    before_count = _count_activities()
    original = activity_service.get_activity(aid)
    orig_end = original["end_time"]
    orig_duration = int(original["duration_seconds"])
    real_get_connection = activity_service.get_connection

    class _FailingInsertConn:
        """Wraps a real connection. The INSERT into ``activity_log`` inside
        ``split_activity`` raises ``sqlite3.OperationalError`` so the
        transaction rolls back. All other statements (SELECT, UPDATE)
        delegate to the real connection."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, params=()):
            stripped = " ".join(sql.split())
            if "INSERT INTO activity_log" in stripped:
                import sqlite3

                raise sqlite3.OperationalError("simulated insert failure")
            return self._real.execute(sql, params)

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    def patched_get_connection():
        return _FailingInsertConn(real_get_connection())

    with patch.object(
        activity_service, "get_connection", side_effect=patched_get_connection
    ):
        with pytest.raises(Exception):
            activity_service.split_activity(aid, "2026-06-25 09:15:00")
    # The transaction must have rolled back: no new activity, original
    # unchanged.
    assert _count_activities() == before_count
    after = activity_service.get_activity(aid)
    assert after["end_time"] == orig_end
    assert int(after["duration_seconds"]) == orig_duration


def test_service_split_activity_assignment_copy_failure_rolls_back(temp_db):
    """If copying the ``activity_project_assignment`` row fails, the
    transaction must roll back so the original activity is unchanged and
    no new activity (or half-created assignment) is persisted."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    before_count = _count_activities()
    original = activity_service.get_activity(aid)
    orig_end = original["end_time"]
    orig_duration = int(original["duration_seconds"])
    real_get_connection = activity_service.get_connection

    class _FailingAssignmentCopyConn:
        """Wraps a real connection. The INSERT into
        ``activity_project_assignment`` inside ``split_activity`` raises so
        the transaction rolls back. All other statements delegate."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, params=()):
            stripped = " ".join(sql.split())
            if "INSERT INTO activity_project_assignment" in stripped:
                import sqlite3

                raise sqlite3.OperationalError("simulated assignment copy failure")
            return self._real.execute(sql, params)

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    def patched_get_connection():
        return _FailingAssignmentCopyConn(real_get_connection())

    with patch.object(
        activity_service, "get_connection", side_effect=patched_get_connection
    ):
        with pytest.raises(Exception):
            activity_service.split_activity(aid, "2026-06-25 09:15:00")
    # The transaction must have rolled back: no new activity, original
    # unchanged.
    assert _count_activities() == before_count
    after = activity_service.get_activity(aid)
    assert after["end_time"] == orig_end
    assert int(after["duration_seconds"]) == orig_duration


def test_service_split_activity_resource_copy_failure_rolls_back(temp_db):
    """If copying the ``activity_resource`` row fails, the transaction must
    roll back so the original activity is unchanged and no new activity (or
    half-created resource) is persisted."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    before_count = _count_activities()
    original = activity_service.get_activity(aid)
    orig_end = original["end_time"]
    orig_duration = int(original["duration_seconds"])
    real_get_connection = activity_service.get_connection

    class _FailingResourceCopyConn:
        """Wraps a real connection. The INSERT into ``activity_resource``
        inside ``split_activity`` raises so the transaction rolls back. All
        other statements delegate."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, params=()):
            stripped = " ".join(sql.split())
            if "INSERT INTO activity_resource" in stripped:
                import sqlite3

                raise sqlite3.OperationalError("simulated resource copy failure")
            return self._real.execute(sql, params)

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    def patched_get_connection():
        return _FailingResourceCopyConn(real_get_connection())

    with patch.object(
        activity_service, "get_connection", side_effect=patched_get_connection
    ):
        with pytest.raises(Exception):
            activity_service.split_activity(aid, "2026-06-25 09:15:00")
    # The transaction must have rolled back: no new activity, original
    # unchanged.
    assert _count_activities() == before_count
    after = activity_service.get_activity(aid)
    assert after["end_time"] == orig_end
    assert int(after["duration_seconds"]) == orig_duration
