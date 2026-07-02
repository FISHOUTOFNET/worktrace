"""Tests for the Timeline time-correction API layer.

Covers ``worktrace.api.timeline_api.update_timeline_activity_time`` and
``worktrace.api.timeline_api.update_timeline_session_time``:

- input validation (non-positive id, bool id, nonexistent id, deleted
  activity, non-string time, bad time format, start >= end);
- successful writes (single-activity time correction, duration_seconds
  recomputation, single-activity session-level correction);
- in-progress activity rejection;
- cross-day activity modification and timeline_service report_date
  projection;
- multi-activity session-level rejection;
- no partial writes on validation failure.
"""

from __future__ import annotations

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineTimeEditError
from worktrace.services import activity_service


def _activity(app, process, title, start, project_id=None, status="normal"):
    aid = activity_service.create_activity(
        app,
        process,
        title,
        start_time=f"2026-06-25 {start}",
        project_id=project_id,
        status=status,
    )
    activity_service.finalize_created_activity(aid)
    return aid


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


def _seed_session(project_id=None):
    """Seed a simple two-activity session on 2026-06-25."""
    a1 = _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_id)
    a2 = _activity("Word", "winword.exe", "A2.docx", "09:10:00", project_id)
    activity_service.close_activity(a2, "2026-06-25 09:30:00")
    return [a1, a2]




def test_update_activity_time_non_positive_id(temp_db):
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(0, "2026-06-25 09:00:00", "2026-06-25 09:30:00")
    assert exc.value.code == "invalid_id"
    with pytest.raises(TimelineTimeEditError) as exc2:
        timeline_api.update_timeline_activity_time(-1, "2026-06-25 09:00:00", "2026-06-25 09:30:00")
    assert exc2.value.code == "invalid_id"


def test_update_activity_time_bool_id(temp_db):
    """``bool`` is a subclass of ``int``; it must be rejected so ``True``
    does not silently coerce to ``1``."""
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(True, "2026-06-25 09:00:00", "2026-06-25 09:30:00")
    assert exc.value.code == "invalid_id"
    with pytest.raises(TimelineTimeEditError) as exc2:
        timeline_api.update_timeline_activity_time(False, "2026-06-25 09:00:00", "2026-06-25 09:30:00")
    assert exc2.value.code == "invalid_id"


def test_update_activity_time_nonexistent_id(temp_db):
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(999999, "2026-06-25 09:00:00", "2026-06-25 09:30:00")
    assert exc.value.code == "invalid_id"


def test_update_activity_time_deleted_activity(temp_db):
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(aid, "2026-06-25 09:00:00", "2026-06-25 09:30:00")
    assert exc.value.code == "invalid_id"


def test_update_activity_time_non_string_time(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(aid, 12345, "2026-06-25 09:30:00")
    assert exc.value.code == "invalid_time"
    with pytest.raises(TimelineTimeEditError) as exc2:
        timeline_api.update_timeline_activity_time(aid, "2026-06-25 09:00:00", None)
    assert exc2.value.code == "invalid_time"


def test_update_activity_time_bad_format(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(aid, "not-a-time", "2026-06-25 09:30:00")
    assert exc.value.code == "invalid_time"
    with pytest.raises(TimelineTimeEditError) as exc2:
        timeline_api.update_timeline_activity_time(aid, "2026-06-25 09:00:00", "2026/06/25 09:30:00")
    assert exc2.value.code == "invalid_time"
    # Missing seconds
    with pytest.raises(TimelineTimeEditError) as exc3:
        timeline_api.update_timeline_activity_time(aid, "2026-06-25 09:00", "2026-06-25 09:30:00")
    assert exc3.value.code == "invalid_time"


def test_update_activity_time_start_ge_end(temp_db):
    """Zero and negative durations must be rejected."""
    aid = _seed_closed_activity()
    # Equal (zero duration)
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(aid, "2026-06-25 09:00:00", "2026-06-25 09:00:00")
    assert exc.value.code == "invalid_time"
    # End before start (negative duration)
    with pytest.raises(TimelineTimeEditError) as exc2:
        timeline_api.update_timeline_activity_time(aid, "2026-06-25 09:30:00", "2026-06-25 09:00:00")
    assert exc2.value.code == "invalid_time"


def test_update_activity_time_in_progress(temp_db):
    """An open activity (``end_time IS NULL``) cannot be time-edited."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    # Activity is still open (not closed)
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(aid, "2026-06-25 09:00:00", "2026-06-25 09:30:00")
    assert exc.value.code == "in_progress"




def test_update_activity_time_success(temp_db):
    aid = _seed_closed_activity()
    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    activity = activity_service.get_activity(aid)
    assert activity["start_time"] == "2026-06-25 10:00:00"
    assert activity["end_time"] == "2026-06-25 10:45:00"


def test_update_activity_time_recomputes_duration(temp_db):
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    # Original duration should be 1800 seconds (30 min)
    before = activity_service.get_activity(aid)
    assert int(before["duration_seconds"]) == 1800
    # Change to 10:00 - 10:45 (45 min = 2700 seconds)
    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    after = activity_service.get_activity(aid)
    assert int(after["duration_seconds"]) == 2700


def test_update_activity_time_does_not_mutate_other_fields(temp_db):
    """Time correction must not alter project_id, note, or other fields."""
    from worktrace.services import project_service

    project = project_service.create_project("TestProj")
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A.docx",
        start_time="2026-06-25 09:00:00",
        project_id=project,
        note="my note",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-25 09:30:00")

    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    after = activity_service.get_activity(aid)
    assert int(after["project_id"]) == project
    assert after.get("note") == "my note"




def test_update_activity_time_cross_day_assigned_to_correct_report_dates(temp_db):
    """An activity modified to span midnight must be split by
    timeline_service into the correct report_dates."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00", day="2026-06-25")
    # Modify to cross midnight: 2026-06-25 23:00 -> 2026-06-26 01:00
    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 23:00:00", "2026-06-26 01:00:00"
    )
    # The raw DB row should reflect the new times
    activity = activity_service.get_activity(aid)
    assert activity["start_time"] == "2026-06-25 23:00:00"
    assert activity["end_time"] == "2026-06-26 01:00:00"
    # timeline_service should project this activity onto both days
    sessions_day1 = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    sessions_day2 = timeline_api.get_project_sessions_by_date(
        "2026-06-26", include_hidden=False, ensure_context=True
    )
    day1_has = any(aid in (s.get("activity_ids") or []) for s in sessions_day1)
    day2_has = any(aid in (s.get("activity_ids") or []) for s in sessions_day2)
    assert day1_has, "cross-day activity must appear on 2026-06-25"
    assert day2_has, "cross-day activity must appear on 2026-06-26"


def test_update_activity_time_back_to_single_day(temp_db):
    """After extending an activity across midnight and then pulling it
    back to a single day, it must only appear on that day."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00", day="2026-06-25")
    # Extend to cross midnight
    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 23:00:00", "2026-06-26 01:00:00"
    )
    # Pull back to single day
    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 23:00:00", "2026-06-25 23:30:00"
    )
    sessions_day2 = timeline_api.get_project_sessions_by_date(
        "2026-06-26", include_hidden=False, ensure_context=True
    )
    day2_has = any(aid in (s.get("activity_ids") or []) for s in sessions_day2)
    assert not day2_has, "activity pulled back must not appear on 2026-06-26"




def test_update_session_time_single_activity_success(temp_db):
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    timeline_api.update_timeline_session_time(
        [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    activity = activity_service.get_activity(aid)
    assert activity["start_time"] == "2026-06-25 10:00:00"
    assert activity["end_time"] == "2026-06-25 10:45:00"
    assert int(activity["duration_seconds"]) == 2700


def test_update_session_time_multi_activity_rejected(temp_db):
    """A session with more than one activity must raise ``multi_activity``."""
    ids = _seed_session()
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_session_time(
            ids, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )
    assert exc.value.code == "multi_activity"


def test_update_session_time_dedup_single_activity(temp_db):
    """Duplicate ids that resolve to one activity should succeed."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    timeline_api.update_timeline_session_time(
        [aid, aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    activity = activity_service.get_activity(aid)
    assert activity["start_time"] == "2026-06-25 10:00:00"


def test_update_session_time_empty_list(temp_db):
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_time(
            [], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )


def test_update_session_time_in_progress(temp_db):
    """A single-activity session that is still open must raise
    ``in_progress``."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_session_time(
            [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )
    assert exc.value.code == "in_progress"


def test_update_session_time_deleted_activity(temp_db):
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_time(
            [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )


def test_update_session_time_bad_time_format(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_session_time(
            [aid], "bad", "2026-06-25 10:45:00"
        )
    assert exc.value.code == "invalid_time"


def test_update_session_time_start_ge_end(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_session_time(
            [aid], "2026-06-25 10:45:00", "2026-06-25 10:00:00"
        )
    assert exc.value.code == "invalid_time"




def test_update_activity_time_no_partial_write_on_bad_time(temp_db):
    """If the time validation fails, the original activity must be
    untouched."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    original = activity_service.get_activity(aid)
    with pytest.raises(TimelineTimeEditError):
        timeline_api.update_timeline_activity_time(
            aid, "2026-06-25 10:45:00", "2026-06-25 10:00:00"
        )
    after = activity_service.get_activity(aid)
    assert after["start_time"] == original["start_time"]
    assert after["end_time"] == original["end_time"]
    assert int(after["duration_seconds"]) == int(original["duration_seconds"])


def test_update_session_time_no_partial_write_on_multi_activity(temp_db):
    """If a multi-activity session is rejected, no activity in the session
    must be modified."""
    ids = _seed_session()
    originals = {aid: activity_service.get_activity(aid) for aid in ids}
    with pytest.raises(TimelineTimeEditError):
        timeline_api.update_timeline_session_time(
            ids, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert after["start_time"] == originals[aid]["start_time"]
        assert after["end_time"] == originals[aid]["end_time"]


def test_update_activity_time_reread_timeline_reflects_change(temp_db):
    """After a time correction, re-reading the timeline must show the new
    times in the session list."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 14:00:00", "2026-06-25 14:45:00"
    )
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    found = False
    for s in sessions:
        if aid in (s.get("activity_ids") or []):
            # The session's start_time should reflect the new time
            assert str(s.get("start_time") or "").startswith("2026-06-25 14:00:00")
            found = True
            break
    assert found, "modified activity must still appear in the timeline"




def test_update_activity_time_t_separator_rejected(temp_db):
    """The ISO ``T`` separator must be rejected; only ``YYYY-MM-DD HH:MM:SS``
    (space separator) is accepted."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(
            aid, "2026-06-25T09:00:00", "2026-06-25 09:30:00"
        )
    assert exc.value.code == "invalid_time"
    with pytest.raises(TimelineTimeEditError) as exc2:
        timeline_api.update_timeline_activity_time(
            aid, "2026-06-25 09:00:00", "2026-06-25T09:30:00"
        )
    assert exc2.value.code == "invalid_time"


def test_update_activity_time_timezone_string_rejected(temp_db):
    """Timezone suffixes must be rejected; only naive ``YYYY-MM-DD HH:MM:SS``
    is accepted."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineTimeEditError) as exc:
        timeline_api.update_timeline_activity_time(
            aid, "2026-06-25 09:00:00+08:00", "2026-06-25 09:30:00"
        )
    assert exc.value.code == "invalid_time"
    with pytest.raises(TimelineTimeEditError) as exc2:
        timeline_api.update_timeline_activity_time(
            aid, "2026-06-25 09:00:00Z", "2026-06-25 09:30:00"
        )
    assert exc2.value.code == "invalid_time"


def test_update_activity_time_duration_precisely_equals_second_diff(temp_db):
    """``duration_seconds`` must exactly equal the second difference between
    ``end_time`` and ``start_time``."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    # 1 hour 23 minutes 45 seconds = 5025 seconds
    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 10:00:00", "2026-06-25 11:23:45"
    )
    activity = activity_service.get_activity(aid)
    assert int(activity["duration_seconds"]) == 5025


def test_service_update_activity_time_raises_on_deleted_activity(temp_db):
    """The service layer must raise when the UPDATE hits 0 rows because the
    activity was deleted (race condition defense)."""
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    with pytest.raises(ValueError):
        activity_service.update_activity_time(
            aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )


def test_service_update_activity_time_raises_on_in_progress_activity(temp_db):
    """The service layer must raise when the UPDATE hits 0 rows because the
    activity was reopened (``end_time IS NULL``)."""
    aid = _seed_closed_activity()
    activity_service.reopen_activity(aid)
    with pytest.raises(ValueError):
        activity_service.update_activity_time(
            aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )


def test_api_update_activity_time_handles_race_condition(temp_db):
    """If the activity is deleted between API validation and the service
    write, the API must raise ``TimelineTimeEditError("invalid_id")``
    instead of silently succeeding."""
    from unittest.mock import patch

    aid = _seed_closed_activity()
    original_update = activity_service.update_activity_time

    def racing_update(activity_id, start_time, end_time):
        # Simulate the activity being deleted between validation and write
        activity_service.soft_delete_activity(activity_id)
        return original_update(activity_id, start_time, end_time)

    with patch.object(
        activity_service, "update_activity_time", side_effect=racing_update
    ):
        with pytest.raises(TimelineTimeEditError) as exc:
            timeline_api.update_timeline_activity_time(
                aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
            )
    assert exc.value.code == "invalid_id"


def test_api_update_session_time_handles_race_condition(temp_db):
    """If the single activity is deleted between API validation and the
    service write, ``update_timeline_session_time`` must raise
    ``TimelineTimeEditError("invalid_id")``."""
    from unittest.mock import patch

    aid = _seed_closed_activity()
    original_update = activity_service.update_activity_time

    def racing_update(activity_id, start_time, end_time):
        activity_service.soft_delete_activity(activity_id)
        return original_update(activity_id, start_time, end_time)

    with patch.object(
        activity_service, "update_activity_time", side_effect=racing_update
    ):
        with pytest.raises(TimelineTimeEditError) as exc:
            timeline_api.update_timeline_session_time(
                [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
            )
    assert exc.value.code == "invalid_id"


def test_update_activity_time_validation_failure_leaves_original_unchanged(temp_db):
    """If validation fails, the original ``start_time``, ``end_time``, and
    ``duration_seconds`` must be untouched."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    original = activity_service.get_activity(aid)
    orig_start = original["start_time"]
    orig_end = original["end_time"]
    orig_duration = int(original["duration_seconds"])
    # Bad time format
    with pytest.raises(TimelineTimeEditError):
        timeline_api.update_timeline_activity_time(
            aid, "not-a-time", "2026-06-25 10:45:00"
        )
    after = activity_service.get_activity(aid)
    assert after["start_time"] == orig_start
    assert after["end_time"] == orig_end
    assert int(after["duration_seconds"]) == orig_duration
    # start >= end
    with pytest.raises(TimelineTimeEditError):
        timeline_api.update_timeline_activity_time(
            aid, "2026-06-25 10:45:00", "2026-06-25 10:00:00"
        )
    after2 = activity_service.get_activity(aid)
    assert after2["start_time"] == orig_start
    assert after2["end_time"] == orig_end
    assert int(after2["duration_seconds"]) == orig_duration


def test_cross_day_activity_slice_duration_reasonable(temp_db):
    """A cross-day activity must produce reasonable duration slices on both
    report_dates when read back through timeline_service."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00", day="2026-06-25")
    # Modify to span midnight: 2026-06-25 23:00 -> 2026-06-26 01:00 (2h total)
    timeline_api.update_timeline_activity_time(
        aid, "2026-06-25 23:00:00", "2026-06-26 01:00:00"
    )
    sessions_day1 = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    sessions_day2 = timeline_api.get_project_sessions_by_date(
        "2026-06-26", include_hidden=False, ensure_context=True
    )
    day1_duration = 0
    day2_duration = 0
    for s in sessions_day1:
        if aid in (s.get("activity_ids") or []):
            day1_duration = int(s.get("duration_seconds") or 0)
    for s in sessions_day2:
        if aid in (s.get("activity_ids") or []):
            day2_duration = int(s.get("duration_seconds") or 0)
    # Day 1 slice: 23:00-24:00 = 3600 seconds (1 hour)
    assert day1_duration == 3600, f"day1 slice should be 3600s, got {day1_duration}"
    # Day 2 slice: 00:00-01:00 = 3600 seconds (1 hour)
    assert day2_duration == 3600, f"day2 slice should be 3600s, got {day2_duration}"
