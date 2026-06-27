"""Tests for the Phase 3B.8 Timeline single activity restore API and
service layer.

Covers ``worktrace.api.timeline_api.restore_timeline_activity``,
``get_timeline_restorable_activities``, and the underlying
``worktrace.services.activity_service.restore_activity`` /
``list_restorable_activities_for_date`` reads / writes:

- input validation (bool id, non-int id, non-positive id, nonexistent id,
  normal non-hidden/non-deleted activity, in-progress activity);
- successful restore of a hidden activity (sets ``is_hidden = 0``);
- successful restore of a soft-deleted activity (sets ``is_deleted = 0``);
- successful restore of a hidden+deleted activity (sets both to 0);
- restore does not modify start/end/duration/project/note/status/source;
- restore does not delete assignment / resource / session-note rows;
- restore does not physically delete the row;
- service UPDATE rowcount 0 maps to ``operation_failed``;
- recovery list returns hidden / deleted / hidden+deleted activities;
- recovery list excludes normal and in-progress activities;
- recovery list is sorted by start_time;
- recovery list returns only display-safe fields;
- recovery list invalid date stable error;
- validation failure leaves the original activity completely unchanged.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineRestoreActivityError
from worktrace.db import get_connection
from worktrace.services import activity_service


# --- Seed helpers --------------------------------------------------------


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


# --- restore_timeline_activity: validation --------------------------------


def test_restore_activity_bool_id(temp_db):
    """``bool`` is a subclass of ``int``; it must be rejected."""
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.restore_timeline_activity(True)
    assert exc.value.code == "invalid_activity"


def test_restore_activity_non_int_id(temp_db):
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.restore_timeline_activity("not an int")
    assert exc.value.code == "invalid_activity"


def test_restore_activity_non_positive_id(temp_db):
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.restore_timeline_activity(0)
    assert exc.value.code == "invalid_activity"


def test_restore_activity_nonexistent_id(temp_db):
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.restore_timeline_activity(999999)
    assert exc.value.code == "not_found"


def test_restore_activity_normal_not_restorable(temp_db):
    """A normal (non-hidden, non-deleted) activity cannot be restored."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.restore_timeline_activity(aid)
    assert exc.value.code == "not_restorable"


def test_restore_activity_in_progress(temp_db):
    """An in-progress activity (raw ``end_time IS NULL``) cannot be
    restored, even if it is hidden or deleted."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    # Manually mark as hidden to simulate a hidden in-progress activity.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (aid,),
        )
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.restore_timeline_activity(aid)
    assert exc.value.code == "in_progress"


# --- restore_timeline_activity: success -----------------------------------


def test_restore_hidden_activity_success(temp_db):
    """Restoring a hidden activity sets ``is_hidden = 0``."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    result = timeline_api.restore_timeline_activity(aid)
    assert result["restored"] is True
    assert result["activity_id"] == aid
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 0
    assert int(activity.get("is_deleted") or 0) == 0


def test_restore_soft_deleted_activity_success(temp_db):
    """Restoring a soft-deleted activity sets ``is_deleted = 0``."""
    aid = _seed_closed_activity()
    timeline_api.soft_delete_timeline_activity(aid)
    result = timeline_api.restore_timeline_activity(aid)
    assert result["restored"] is True
    assert result["activity_id"] == aid
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_deleted") or 0) == 0
    assert int(activity.get("is_hidden") or 0) == 0


def test_restore_hidden_and_deleted_activity_success(temp_db):
    """Restoring a hidden+deleted activity sets both ``is_hidden = 0`` and
    ``is_deleted = 0``."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    timeline_api.soft_delete_timeline_activity(aid)
    # Verify both flags are set.
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1
    assert int(activity.get("is_deleted") or 0) == 1
    result = timeline_api.restore_timeline_activity(aid)
    assert result["restored"] is True
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 0
    assert int(activity.get("is_deleted") or 0) == 0


def test_restore_activity_does_not_modify_core_fields(temp_db):
    """Restore must not touch start/end/duration/project/note/status/source."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    before = activity_service.get_activity(aid)
    timeline_api.restore_timeline_activity(aid)
    after = activity_service.get_activity(aid)
    assert after["start_time"] == before["start_time"]
    assert after["end_time"] == before["end_time"]
    assert int(after["duration_seconds"] or 0) == int(before["duration_seconds"] or 0)
    assert after["project_id"] == before["project_id"]
    assert after["note"] == before["note"]
    assert after["status"] == before["status"]
    assert after["source"] == before["source"]


def test_restore_activity_preserves_assignments(temp_db):
    """Restore must not delete activity_project_assignment rows."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    before = _count_assignments(aid)
    assert before >= 1
    timeline_api.restore_timeline_activity(aid)
    after = _count_assignments(aid)
    assert after == before


def test_restore_activity_preserves_resources(temp_db):
    """Restore must not delete activity_resource rows."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    before = _count_resources(aid)
    assert before >= 1
    timeline_api.restore_timeline_activity(aid)
    after = _count_resources(aid)
    assert after == before


def test_restore_activity_preserves_session_note(temp_db):
    """Restore must not delete project_session_note rows."""
    aid = _seed_closed_activity()
    timeline_api.update_timeline_session_note("2026-06-25", aid, "session note")
    assert _get_session_note("2026-06-25", aid) == "session note"
    timeline_api.hide_timeline_activity(aid)
    timeline_api.restore_timeline_activity(aid)
    assert _get_session_note("2026-06-25", aid) == "session note"


def test_restore_activity_does_not_physically_delete(temp_db):
    """The DB row must still exist after a restore."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    before_count = _count_activities()
    timeline_api.restore_timeline_activity(aid)
    after_count = _count_activities()
    assert after_count == before_count
    assert activity_service.get_activity(aid) is not None


def test_restore_activity_reappears_in_default_timeline(temp_db):
    """After restore, the activity must reappear in the default Timeline
    (``include_hidden=False``)."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    sessions_hidden = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    assert not any(aid in (s.get("activity_ids") or []) for s in sessions_hidden)
    timeline_api.restore_timeline_activity(aid)
    sessions_restored = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    assert any(aid in (s.get("activity_ids") or []) for s in sessions_restored)


# --- restore_timeline_activity: already-restored is not_restorable ---------


def test_restore_already_restored_rejects(temp_db):
    """Restoring an already-restored activity is rejected as
    ``not_restorable`` (restore is not a no-op)."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    timeline_api.restore_timeline_activity(aid)
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.restore_timeline_activity(aid)
    assert exc.value.code == "not_restorable"


# --- Race condition / operation_failed ------------------------------------


def test_restore_activity_race_condition_operation_failed(temp_db):
    """If the service-layer ``restore_activity`` raises ``ValueError`` (race
    condition: the activity was restored or re-opened between validation
    and write), the API must map it to ``operation_failed``."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    with patch.object(
        activity_service, "restore_activity", side_effect=ValueError("restore_failed")
    ):
        with pytest.raises(TimelineRestoreActivityError) as exc:
            timeline_api.restore_timeline_activity(aid)
    assert exc.value.code == "operation_failed"


def test_restore_activity_unknown_exception_operation_failed(temp_db):
    """A non-ValueError service exception must collapse to
    ``operation_failed``."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    with patch.object(
        activity_service, "restore_activity", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(TimelineRestoreActivityError) as exc:
            timeline_api.restore_timeline_activity(aid)
    assert exc.value.code == "operation_failed"


def test_restore_activity_does_not_leak_exception_text(temp_db):
    """The API error must not echo the service exception text."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    with patch.object(
        activity_service, "restore_activity", side_effect=ValueError("secret_internal_detail")
    ):
        with pytest.raises(TimelineRestoreActivityError) as exc:
            timeline_api.restore_timeline_activity(aid)
    assert "secret_internal_detail" not in str(exc.value)
    assert exc.value.code == "operation_failed"


# --- No partial writes on validation failure ------------------------------


def test_restore_activity_validation_failure_leaves_activity_unchanged(temp_db):
    """If validation fails, the activity must be completely unchanged."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    before = activity_service.get_activity(aid)
    before_count = _count_activities()
    with pytest.raises(TimelineRestoreActivityError):
        timeline_api.restore_timeline_activity(0)
    after = activity_service.get_activity(aid)
    assert after == before
    assert _count_activities() == before_count


# --- Service layer rowcount guard -----------------------------------------


def test_service_restore_activity_zero_rowcount_raises(temp_db):
    """``restore_activity`` on a nonexistent id raises ``ValueError``
    (caught earlier as ``activity_not_found``)."""
    with pytest.raises(ValueError) as exc:
        activity_service.restore_activity(999999)
    assert str(exc.value) == "activity_not_found"


def test_service_restore_activity_normal_rejects(temp_db):
    """``restore_activity`` on a normal activity raises
    ``activity_not_restorable``."""
    aid = _seed_closed_activity()
    with pytest.raises(ValueError) as exc:
        activity_service.restore_activity(aid)
    assert str(exc.value) == "activity_not_restorable"


def test_service_restore_activity_in_progress_rejects(temp_db):
    """``restore_activity`` on a hidden in-progress activity raises
    ``activity_in_progress``."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (aid,),
        )
    with pytest.raises(ValueError) as exc:
        activity_service.restore_activity(aid)
    assert str(exc.value) == "activity_in_progress"


def test_service_restore_activity_bool_id_rejects(temp_db):
    with pytest.raises(ValueError) as exc:
        activity_service.restore_activity(True)
    assert str(exc.value) == "invalid_activity_id"


def test_service_restore_activity_non_int_id_rejects(temp_db):
    with pytest.raises(ValueError) as exc:
        activity_service.restore_activity("not an int")
    assert str(exc.value) == "invalid_activity_id"


def test_service_restore_activity_non_positive_id_rejects(temp_db):
    with pytest.raises(ValueError) as exc:
        activity_service.restore_activity(0)
    assert str(exc.value) == "invalid_activity_id"


# --- get_timeline_restorable_activities: success --------------------------


def test_get_restorable_activities_returns_hidden(temp_db):
    """The recovery list includes hidden activities."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    result = timeline_api.get_timeline_restorable_activities("2026-06-25")
    activities = result["activities"]
    assert any(a["activity_id"] == aid for a in activities)
    activity = next(a for a in activities if a["activity_id"] == aid)
    assert activity["restore_state"] == "hidden"
    assert int(activity["is_hidden"]) == 1
    assert int(activity["is_deleted"]) == 0


def test_get_restorable_activities_returns_deleted(temp_db):
    """The recovery list includes soft-deleted activities."""
    aid = _seed_closed_activity()
    timeline_api.soft_delete_timeline_activity(aid)
    result = timeline_api.get_timeline_restorable_activities("2026-06-25")
    activities = result["activities"]
    assert any(a["activity_id"] == aid for a in activities)
    activity = next(a for a in activities if a["activity_id"] == aid)
    assert activity["restore_state"] == "deleted"
    assert int(activity["is_hidden"]) == 0
    assert int(activity["is_deleted"]) == 1


def test_get_restorable_activities_returns_hidden_and_deleted(temp_db):
    """The recovery list includes hidden+deleted activities with the
    ``hidden+deleted`` restore_state."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    timeline_api.soft_delete_timeline_activity(aid)
    result = timeline_api.get_timeline_restorable_activities("2026-06-25")
    activities = result["activities"]
    assert any(a["activity_id"] == aid for a in activities)
    activity = next(a for a in activities if a["activity_id"] == aid)
    assert activity["restore_state"] == "hidden+deleted"
    assert int(activity["is_hidden"]) == 1
    assert int(activity["is_deleted"]) == 1


def test_get_restorable_activities_excludes_normal(temp_db):
    """The recovery list excludes normal (non-hidden, non-deleted)
    activities."""
    aid = _seed_closed_activity()
    result = timeline_api.get_timeline_restorable_activities("2026-06-25")
    activities = result["activities"]
    assert not any(a["activity_id"] == aid for a in activities)


def test_get_restorable_activities_excludes_in_progress(temp_db):
    """The recovery list excludes in-progress hidden/deleted activities."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (aid,),
        )
    result = timeline_api.get_timeline_restorable_activities("2026-06-25")
    activities = result["activities"]
    assert not any(a["activity_id"] == aid for a in activities)


def test_get_restorable_activities_sorted_by_start_time(temp_db):
    """The recovery list is sorted by start_time then id."""
    a2 = _seed_closed_activity(start="10:00:00", end="10:30:00")
    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    timeline_api.hide_timeline_activity(a1)
    timeline_api.hide_timeline_activity(a2)
    result = timeline_api.get_timeline_restorable_activities("2026-06-25")
    activities = result["activities"]
    assert len(activities) == 2
    assert activities[0]["activity_id"] == a1
    assert activities[1]["activity_id"] == a2


def test_get_restorable_activities_display_safe_fields_only(temp_db):
    """The recovery list must not return raw window_title, file_path_hint,
    full_path, clipboard, or note."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    result = timeline_api.get_timeline_restorable_activities("2026-06-25")
    activities = result["activities"]
    assert len(activities) == 1
    activity = activities[0]
    # Display-safe fields must be present.
    for key in (
        "activity_id", "start_time", "end_time", "duration_seconds",
        "app_name", "resource_kind", "resource_subtype",
        "resource_display_name", "project_name", "status",
        "restore_state", "is_hidden", "is_deleted",
    ):
        assert key in activity, f"recovery list must include '{key}'"
    # Sensitive raw fields must be absent.
    for key in (
        "window_title", "file_path_hint", "full_path", "clipboard",
        "note", "traceback", "exception", "sql",
    ):
        assert key not in activity, (
            f"recovery list must not expose sensitive field '{key}'"
        )


def test_get_restorable_activities_invalid_date(temp_db):
    """An invalid date string raises ``TimelineRestoreActivityError`` with
    code ``invalid_date``."""
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.get_timeline_restorable_activities("not-a-date")
    assert exc.value.code == "invalid_date"


def test_get_restorable_activities_empty_date(temp_db):
    with pytest.raises(TimelineRestoreActivityError) as exc:
        timeline_api.get_timeline_restorable_activities("")
    assert exc.value.code == "invalid_date"


def test_get_restorable_activities_no_write(temp_db):
    """The recovery list read path must not modify any data."""
    aid = _seed_closed_activity()
    timeline_api.hide_timeline_activity(aid)
    before = activity_service.get_activity(aid)
    before_count = _count_activities()
    timeline_api.get_timeline_restorable_activities("2026-06-25")
    after = activity_service.get_activity(aid)
    assert after == before
    assert _count_activities() == before_count


def test_get_restorable_activities_excludes_other_dates(temp_db):
    """The recovery list only returns activities for the given date."""
    a1 = _seed_closed_activity(day="2026-06-25")
    a2 = _seed_closed_activity(day="2026-06-26", start="09:00:00", end="09:30:00")
    timeline_api.hide_timeline_activity(a1)
    timeline_api.hide_timeline_activity(a2)
    result_25 = timeline_api.get_timeline_restorable_activities("2026-06-25")
    result_26 = timeline_api.get_timeline_restorable_activities("2026-06-26")
    assert any(a["activity_id"] == a1 for a in result_25["activities"])
    assert not any(a["activity_id"] == a2 for a in result_25["activities"])
    assert any(a["activity_id"] == a2 for a in result_26["activities"])
    assert not any(a["activity_id"] == a1 for a in result_26["activities"])
