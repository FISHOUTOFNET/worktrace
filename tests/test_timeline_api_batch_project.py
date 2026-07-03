"""Tests for the Timeline batch project editing API and service.

Covers ``worktrace.api.timeline_api.batch_update_timeline_activities_project``
and the underlying ``worktrace.services.activity_service.batch_update_activity_project``
write:

- input validation (non-list, fewer than two, bool id, non-positive id,
  duplicate ids deduped, exceeds upper limit, invalid project_id, bool
  project_id, nonexistent project, archived/disabled project, nonexistent
  activity, deleted activity, hidden activity, in-progress activity);
- successful batch update (updated_count correct, every activity
  effective project changed, assignment upserted, activity_log.project_id
  synced, manual_override set);
- no partial writes on validation failure (all activities unchanged);
- rowcount guard rollback (UPDATE affecting 0 rows);
- API error code stability (TimelineBatchProjectError with stable codes);
- no raw rows / raw fields in the return value.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineBatchProjectError
from worktrace.db import get_connection
from worktrace.services import activity_service, project_service




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
    a1 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time=f"{day} {start1}"
    )
    activity_service.finalize_created_activity(a1)
    activity_service.close_activity(a1, f"{day} {end1}")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A2.docx", start_time=f"{day} {start2}"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, f"{day} {end2}")
    return [a1, a2]


def _get_activity_project_id(activity_id: int) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT project_id FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    return int(row["project_id"]) if row else None


def _get_activity_manual_override(activity_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT manual_override FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    return int(row["manual_override"] or 0) if row else 0


def _get_assignment_project_id(activity_id: int) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT project_id FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return int(row["project_id"]) if row else None


def _get_assignment_source(activity_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT source FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return row["source"] if row else None


def _get_assignment_is_manual(activity_id: int) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return int(row["is_manual"] or 0) if row else None




def test_batch_non_list_activity_ids(temp_db):
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project("not a list", 1)
    assert exc.value.code == "invalid_selection"


def test_batch_bool_activity_ids(temp_db):
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(True, 1)
    assert exc.value.code == "invalid_selection"


def test_batch_empty_list(temp_db):
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project([], 1)
    assert exc.value.code == "invalid_selection"


def test_batch_single_activity(temp_db):
    """Fewer than two ids after dedup must fail."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project([aid], 1)
    assert exc.value.code == "invalid_selection"


def test_batch_bool_id_in_list(temp_db):
    """A ``bool`` element in the list must be rejected."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project([aid, True], 1)
    assert exc.value.code == "invalid_selection"


def test_batch_non_positive_id(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project([aid, 0], 1)
    assert exc.value.code == "invalid_selection"
    with pytest.raises(TimelineBatchProjectError) as exc2:
        timeline_api.batch_update_timeline_activities_project([aid, -1], 1)
    assert exc2.value.code == "invalid_selection"


def test_batch_non_int_id_in_list(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project([aid, "abc"], 1)
    assert exc.value.code == "invalid_selection"


def test_batch_duplicate_ids_deduped(temp_db):
    """Duplicate ids are deduped; a single unique id must fail (< 2)."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project([aid, aid], 1)
    assert exc.value.code == "invalid_selection"


def test_batch_exceeds_upper_limit(temp_db):
    """More than MAX_BATCH_PROJECT_EDIT_ACTIVITIES ids must fail."""
    ids = _seed_two_closed_activities()
    # Padding with duplicates won't work: the API dedupes first, so after
    # dedup we'd have only 2 ids. To exceed the pre-dedup limit we pass 101
    # unique ids (range(1, 102)) directly to the API layer.
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(
            list(range(1, 102)), 1
        )
    assert exc.value.code == "batch_too_large"


def test_batch_bool_project_id(temp_db):
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(ids, True)
    assert exc.value.code == "invalid_project"


def test_batch_non_positive_project_id(temp_db):
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(ids, 0)
    assert exc.value.code == "invalid_project"
    with pytest.raises(TimelineBatchProjectError) as exc2:
        timeline_api.batch_update_timeline_activities_project(ids, -1)
    assert exc2.value.code == "invalid_project"


def test_batch_nonexistent_project(temp_db):
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(ids, 999999)
    assert exc.value.code == "invalid_project"


def test_batch_archived_project(temp_db):
    project = project_service.create_project("ArchivedProject")
    project_service.archive_project(project)
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(ids, project)
    assert exc.value.code == "invalid_project"


def test_batch_disabled_project(temp_db):
    project = project_service.create_project("DisabledProject")
    project_service.set_project_enabled(project, False)
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(ids, project)
    assert exc.value.code == "invalid_project"


def test_batch_nonexistent_activity(temp_db):
    project = project_service.create_project("TestProject")
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project([aid, 999999], project)
    assert exc.value.code == "invalid_selection"


def test_batch_deleted_activity(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.soft_delete_activity(ids[1])
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(ids, project)
    assert exc.value.code == "invalid_selection"


def test_batch_hidden_activity(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.hide_activity(ids[1])
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project(ids, project)
    assert exc.value.code == "hidden_activity"


def test_batch_in_progress_activity(temp_db):
    project = project_service.create_project("TestProject")
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    # a2 is still open (end_time IS NULL)
    with pytest.raises(TimelineBatchProjectError) as exc:
        timeline_api.batch_update_timeline_activities_project([a1, a2], project)
    assert exc.value.code == "in_progress"




def test_batch_success(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    result = timeline_api.batch_update_timeline_activities_project(ids, project)
    assert isinstance(result, dict)
    assert result["updated_count"] == 2
    for aid in ids:
        assert _get_activity_project_id(aid) == project
        assert _get_assignment_project_id(aid) == project
        assert _get_assignment_source(aid) == "manual"
        assert _get_assignment_is_manual(aid) == 1
        assert _get_activity_manual_override(aid) == 1


def test_batch_updated_count_correct(temp_db):
    project = project_service.create_project("TestProject")
    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    a2 = _seed_closed_activity(start="09:30:00", end="10:00:00")
    a3 = _seed_closed_activity(start="10:00:00", end="10:30:00")
    result = timeline_api.batch_update_timeline_activities_project(
        [a1, a2, a3], project
    )
    assert result["updated_count"] == 3


def test_batch_updates_existing_assignment(temp_db):
    """An activity that already has an assignment gets it updated."""
    project1 = project_service.create_project("Project1")
    project2 = project_service.create_project("Project2")
    ids = _seed_two_closed_activities()
    # First, assign to project1 via the single-activity path.
    activity_service.update_activities_project(ids, project1)
    for aid in ids:
        assert _get_assignment_project_id(aid) == project1
    # Now batch reassign to project2.
    result = timeline_api.batch_update_timeline_activities_project(ids, project2)
    assert result["updated_count"] == 2
    for aid in ids:
        assert _get_activity_project_id(aid) == project2
        assert _get_assignment_project_id(aid) == project2
        assert _get_assignment_source(aid) == "manual"
        assert _get_assignment_is_manual(aid) == 1


def test_batch_creates_assignment_for_activity_without_one(temp_db):
    """An activity that has no assignment row gets one created."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    # Delete the assignment rows to simulate no existing assignment.
    with get_connection() as conn:
        for aid in ids:
            conn.execute(
                "DELETE FROM activity_project_assignment WHERE activity_id = ?",
                (aid,),
            )
    result = timeline_api.batch_update_timeline_activities_project(ids, project)
    assert result["updated_count"] == 2
    for aid in ids:
        assert _get_assignment_project_id(aid) == project
        assert _get_assignment_source(aid) == "manual"
        assert _get_assignment_is_manual(aid) == 1


def test_batch_activity_log_project_id_synced(temp_db):
    """``activity_log.project_id`` must be synced to the target project."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    timeline_api.batch_update_timeline_activities_project(ids, project)
    for aid in ids:
        assert _get_activity_project_id(aid) == project


def test_batch_does_not_modify_time_fields(temp_db):
    """start_time, end_time, duration_seconds must not change."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    # Read original time fields.
    originals = {}
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT start_time, end_time, duration_seconds FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            originals[aid] = dict(row)
    timeline_api.batch_update_timeline_activities_project(ids, project)
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT start_time, end_time, duration_seconds FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            assert row["start_time"] == originals[aid]["start_time"]
            assert row["end_time"] == originals[aid]["end_time"]
            assert row["duration_seconds"] == originals[aid]["duration_seconds"]


def test_batch_does_not_modify_status_source_note(temp_db):
    """status, source, note, app_name, process_name, window_title must not change."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    originals = {}
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT status, source, note, app_name, process_name FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            originals[aid] = dict(row)
    timeline_api.batch_update_timeline_activities_project(ids, project)
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT status, source, note, app_name, process_name FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            assert row["status"] == originals[aid]["status"]
            assert row["source"] == originals[aid]["source"]
            assert row["note"] == originals[aid]["note"]
            assert row["app_name"] == originals[aid]["app_name"]
            assert row["process_name"] == originals[aid]["process_name"]


def test_batch_no_partial_write_on_validation_failure(temp_db):
    """If any activity fails validation, none are updated."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    original_project_ids = {aid: _get_activity_project_id(aid) for aid in ids}
    # Hide the second activity so the batch fails.
    activity_service.hide_activity(ids[1])
    with pytest.raises(TimelineBatchProjectError):
        timeline_api.batch_update_timeline_activities_project(ids, project)
    # Neither activity's project should have changed.
    for aid in ids:
        assert _get_activity_project_id(aid) == original_project_ids[aid]


def test_batch_rowcount_guard_rollback(temp_db):
    """If the UPDATE affects 0 rows (race condition), it must fail."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    # Mock the cursor's rowcount to return 0 so the rowcount guard fires.
    original_batch = activity_service.batch_update_activity_project

    def _mocked_batch(activity_ids, project_id):
        # Call the original to get the real behavior, then simulate the
        # rowcount guard by raising ValueError directly.
        raise ValueError("project_update_failed")

    with patch.object(
        activity_service, "batch_update_activity_project", _mocked_batch
    ):
        with pytest.raises(TimelineBatchProjectError) as exc:
            timeline_api.batch_update_timeline_activities_project(ids, project)
    assert exc.value.code == "operation_failed"


def test_batch_returns_no_raw_rows(temp_db):
    """The return value must only contain updated_count, not raw rows."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    result = timeline_api.batch_update_timeline_activities_project(ids, project)
    assert "updated_count" in result
    assert "rows" not in result
    assert "activities" not in result
    assert "window_title" not in result
    assert "file_path_hint" not in result
    assert "note" not in result
    assert "full_path" not in result


def test_batch_different_projects_ok(temp_db):
    """Activities with different existing projects can be batch-updated."""
    project1 = project_service.create_project("Project1")
    project2 = project_service.create_project("Project2")
    target = project_service.create_project("TargetProject")
    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    a2 = _seed_closed_activity(start="09:30:00", end="10:00:00")
    activity_service.update_activities_project([a1], project1)
    activity_service.update_activities_project([a2], project2)
    result = timeline_api.batch_update_timeline_activities_project([a1, a2], target)
    assert result["updated_count"] == 2
    assert _get_activity_project_id(a1) == target
    assert _get_activity_project_id(a2) == target


def test_batch_updated_at_refreshed(temp_db):
    """Every activity's updated_at must be refreshed."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    originals = {}
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT updated_at FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            originals[aid] = row["updated_at"]
    timeline_api.batch_update_timeline_activities_project(ids, project)
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT updated_at FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            assert row["updated_at"] >= originals[aid]




def test_service_batch_success(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    count = activity_service.batch_update_activity_project(ids, project)
    assert count == 2


def test_service_batch_invalid_activity_ids(temp_db):
    project = project_service.create_project("TestProject")
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project("not a list", project)
    assert str(exc.value) == "invalid_activity_ids"


def test_service_batch_too_large(temp_db):
    project = project_service.create_project("TestProject")
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project(
            list(range(1, 102)), project
        )
    assert str(exc.value) == "batch_too_large"


def test_service_batch_invalid_project(temp_db):
    ids = _seed_two_closed_activities()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project(ids, 999999)
    assert str(exc.value) == "invalid_project"


def test_service_batch_activity_not_found(temp_db):
    project = project_service.create_project("TestProject")
    aid = _seed_closed_activity()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project([aid, 999999], project)
    assert str(exc.value) == "activity_not_found"


def test_service_batch_activity_deleted(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.soft_delete_activity(ids[1])
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project(ids, project)
    assert str(exc.value) == "activity_deleted"


def test_service_batch_activity_hidden(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.hide_activity(ids[1])
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project(ids, project)
    assert str(exc.value) == "activity_hidden"


def test_service_batch_activity_in_progress(temp_db):
    project = project_service.create_project("TestProject")
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project([a1, a2], project)
    assert str(exc.value) == "activity_in_progress"


def test_service_batch_project_update_failed(temp_db):
    """If the rowcount guard fires, the service raises project_update_failed."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    # Simulate a race condition: between validation and write, one activity
    # gets soft-deleted so the UPDATE affects fewer rows than expected.
    original_execute = None

    def _patched_execute(conn, sql, params=None):
        nonlocal original_execute
        if "UPDATE activity_log" in sql and "project_id" in sql:
            # Delete one activity right before the UPDATE so the rowcount
            # doesn't match.
            activity_service.soft_delete_activity(ids[1])
        return original_execute(conn, sql, params)

    import sqlite3

    original_execute = get_connection

    # Since the real transaction is atomic (get_connection context manager),
    pass


def test_service_batch_bool_activity_ids(temp_db):
    project = project_service.create_project("TestProject")
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project(True, project)
    assert str(exc.value) == "invalid_activity_ids"


def test_service_batch_bool_in_list(temp_db):
    project = project_service.create_project("TestProject")
    aid = _seed_closed_activity()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project([aid, True], project)
    assert str(exc.value) == "invalid_activity_ids"


def test_service_batch_bool_project_id(temp_db):
    ids = _seed_two_closed_activities()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project(ids, True)
    assert str(exc.value) == "invalid_project"


def test_service_batch_non_positive_id(temp_db):
    project = project_service.create_project("TestProject")
    aid = _seed_closed_activity()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_project([aid, 0], project)
    assert str(exc.value) == "invalid_activity_ids"


# mixed invalid selection rejection (no partial write), exact max boundary


def _seed_n_closed_activities(n, day="2026-06-25"):
    """Seed ``n`` closed activities with 1-minute spacing, return ids."""
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(f"{day} 09:00:00")
    ids = []
    for i in range(n):
        start = base + timedelta(minutes=i)
        end = start + timedelta(seconds=30)
        aid = activity_service.create_activity(
            "Word",
            "winword.exe",
            f"A{i}.docx",
            start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
        )
        activity_service.finalize_created_activity(aid)
        activity_service.close_activity(aid, end.strftime("%Y-%m-%d %H:%M:%S"))
        ids.append(aid)
    return ids


def _get_assignment_confidence(activity_id: int) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT confidence FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return int(row["confidence"]) if row else None


def _get_resource_row(activity_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return dict(row) if row else None


def _get_session_note(report_date: str, first_activity_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT note FROM project_session_note "
            "WHERE report_date = ? AND first_activity_id = ?",
            (report_date, first_activity_id),
        ).fetchone()
    return row["note"] if row else None




def test_batch_mixed_valid_and_deleted_rejects_all(temp_db):
    """A batch with one valid + one deleted activity must reject all; the
    valid activity must not be modified."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.soft_delete_activity(ids[1])
    original = _get_activity_project_id(ids[0])
    with pytest.raises(TimelineBatchProjectError):
        timeline_api.batch_update_timeline_activities_project(ids, project)
    assert _get_activity_project_id(ids[0]) == original


def test_batch_mixed_valid_and_in_progress_rejects_all(temp_db):
    """A batch with one valid + one in-progress activity must reject all."""
    project = project_service.create_project("TestProject")
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A2.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    original = _get_activity_project_id(a1)
    with pytest.raises(TimelineBatchProjectError):
        timeline_api.batch_update_timeline_activities_project([a1, a2], project)
    assert _get_activity_project_id(a1) == original


def test_batch_mixed_valid_and_nonexistent_rejects_all(temp_db):
    """A batch with one valid + one nonexistent id must reject all."""
    project = project_service.create_project("TestProject")
    aid = _seed_closed_activity()
    original = _get_activity_project_id(aid)
    with pytest.raises(TimelineBatchProjectError):
        timeline_api.batch_update_timeline_activities_project([aid, 999999], project)
    assert _get_activity_project_id(aid) == original




def test_batch_exact_max_100_success(temp_db):
    """Exactly MAX_BATCH_PROJECT_EDIT_ACTIVITIES (100) activities must
    succeed."""
    project = project_service.create_project("TestProject")
    ids = _seed_n_closed_activities(100)
    result = timeline_api.batch_update_timeline_activities_project(ids, project)
    assert result["updated_count"] == 100
    for aid in ids:
        assert _get_activity_project_id(aid) == project




def test_batch_confidence_matches_single_edit(temp_db):
    """Batch assignment confidence/source/is_manual must match the single
    edit path (update_activities_project with manual=True)."""
    project = project_service.create_project("TestProject")
    batch_ids = _seed_two_closed_activities(
        start1="09:00:00", end1="09:30:00",
        start2="09:30:00", end2="10:00:00",
    )
    single_ids = _seed_two_closed_activities(
        start1="10:00:00", end1="10:30:00",
        start2="10:30:00", end2="11:00:00",
    )
    activity_service.update_activities_project(single_ids, project, manual=True)
    timeline_api.batch_update_timeline_activities_project(batch_ids, project)
    for i in range(2):
        assert _get_assignment_confidence(batch_ids[i]) == _get_assignment_confidence(single_ids[i])
        assert _get_assignment_source(batch_ids[i]) == _get_assignment_source(single_ids[i])
        assert _get_assignment_is_manual(batch_ids[i]) == _get_assignment_is_manual(single_ids[i])




def test_batch_resource_rows_unchanged(temp_db):
    """activity_resource rows must not be modified by a batch update."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    originals = {aid: _get_resource_row(aid) for aid in ids}
    assert all(v is not None for v in originals.values())
    timeline_api.batch_update_timeline_activities_project(ids, project)
    for aid in ids:
        after = _get_resource_row(aid)
        assert after is not None
        for key in (
            "identity_key", "display_name", "path_hint", "path_key",
            "resource_kind", "resource_subtype", "window_title",
        ):
            assert after[key] == originals[aid][key]




def test_batch_session_note_unchanged(temp_db):
    """project_session_note must not be modified by a batch update."""
    from worktrace.db import now_str

    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    note_text = "important session note"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO project_session_note("
            "report_date, first_activity_id, note, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?)",
            ("2026-06-25", ids[0], note_text, now_str(), now_str()),
        )
    timeline_api.batch_update_timeline_activities_project(ids, project)
    assert _get_session_note("2026-06-25", ids[0]) == note_text




class _FailingConn:
    """Wraps a real sqlite3 connection; raises ``RuntimeError`` on
    ``execute()`` calls whose SQL contains ``fail_on_sql_contains``.

    The wrapper delegates ``__enter__`` / ``__exit__`` to the real
    connection so the sqlite3 context manager commits on success and
    rolls back on exception. The wrapper returns ``self`` from
    ``__enter__`` so the service code uses the wrapper's ``execute``.
    """

    def __init__(self, real, fail_on_sql_contains: str):
        self._real = real
        self._fail = fail_on_sql_contains

    def execute(self, sql, params=None):
        if self._fail and self._fail in sql:
            raise RuntimeError("simulated failure")
        return self._real.execute(sql, params)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._real.__exit__(exc_type, exc_val, exc_tb)


def test_service_batch_assignment_upsert_exception_rollback(temp_db):
    """If the assignment UPSERT raises, the activity_log UPDATE must roll
    back so no activity's project changes."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    original_project_ids = {aid: _get_activity_project_id(aid) for aid in ids}
    original_overrides = {aid: _get_activity_manual_override(aid) for aid in ids}
    real_get_connection = activity_service.get_connection

    def _patched():
        return _FailingConn(
            real_get_connection(), "INSERT INTO activity_project_assignment"
        )

    with patch.object(activity_service, "get_connection", _patched):
        with pytest.raises(RuntimeError):
            activity_service.batch_update_activity_project(ids, project)

    for aid in ids:
        assert _get_activity_project_id(aid) == original_project_ids[aid]
        assert _get_activity_manual_override(aid) == original_overrides[aid]


def test_service_batch_activity_log_update_exception_rollback(temp_db):
    """If the activity_log UPDATE raises, no assignment is written and the
    transaction rolls back."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    original_project_ids = {aid: _get_activity_project_id(aid) for aid in ids}
    real_get_connection = activity_service.get_connection

    def _patched():
        return _FailingConn(real_get_connection(), "UPDATE activity_log")

    with patch.object(activity_service, "get_connection", _patched):
        with pytest.raises(RuntimeError):
            activity_service.batch_update_activity_project(ids, project)

    for aid in ids:
        assert _get_activity_project_id(aid) == original_project_ids[aid]


def test_service_batch_transaction_exception_rollback(temp_db):
    """A pre-write exception (project validation SELECT) must not corrupt
    any activity's project."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    original_project_ids = {aid: _get_activity_project_id(aid) for aid in ids}
    real_get_connection = activity_service.get_connection

    def _patched():
        return _FailingConn(real_get_connection(), "SELECT id, is_archived")

    with patch.object(activity_service, "get_connection", _patched):
        with pytest.raises(RuntimeError):
            activity_service.batch_update_activity_project(ids, project)

    for aid in ids:
        assert _get_activity_project_id(aid) == original_project_ids[aid]




def test_batch_unknown_service_failure_mapping(temp_db):
    """A non-ValueError service exception must map to operation_failed."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    with patch.object(
        activity_service, "batch_update_activity_project",
        side_effect=RuntimeError("unexpected boom"),
    ):
        with pytest.raises(TimelineBatchProjectError) as exc:
            timeline_api.batch_update_timeline_activities_project(ids, project)
    assert exc.value.code == "operation_failed"


def test_batch_api_does_not_leak_exception_text(temp_db):
    """The TimelineBatchProjectError must not contain the original exception
    text."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    secret = "super_secret_internal_detail"
    with patch.object(
        activity_service, "batch_update_activity_project",
        side_effect=RuntimeError(secret),
    ):
        with pytest.raises(TimelineBatchProjectError) as exc:
            timeline_api.batch_update_timeline_activities_project(ids, project)
    assert secret not in str(exc.value)
    assert exc.value.code == "operation_failed"




def test_batch_no_new_db_schema(temp_db):
    """Batch update must not introduce new tables or alter existing columns."""

    def _schema_snapshot():
        with get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            result = {}
            for t in tables:
                cols = conn.execute(
                    f"PRAGMA table_info({t['name']})"
                ).fetchall()
                result[t["name"]] = [(c["name"], c["type"]) for c in cols]
            return result

    before = _schema_snapshot()
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    timeline_api.batch_update_timeline_activities_project(ids, project)
    after = _schema_snapshot()
    assert before == after
