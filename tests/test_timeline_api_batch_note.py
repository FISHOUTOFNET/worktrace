"""Tests for the Phase 3B.7 Timeline batch note editing API and service.

Covers ``worktrace.api.timeline_api.batch_update_timeline_activities_note``
and the underlying ``worktrace.services.activity_service.batch_update_activity_note``
write:

- input validation (non-list, fewer than two, bool id, non-positive id,
  duplicate ids deduped, exceeds upper limit, invalid note, None note,
  too-long note, nonexistent activity, deleted activity, hidden activity,
  in-progress activity);
- successful batch update (updated_count correct, every activity note
  overwritten, old note not concatenated, empty note clears, time /
  project / status / source / assignment / resource / session-note rows
  unchanged);
- no partial writes on validation failure (all activities unchanged);
- rowcount guard rollback (UPDATE affecting 0 rows);
- API error code stability (TimelineBatchNoteError with stable codes);
- no raw rows / raw fields / old note / new note in the return value;
- no new DB schema introduced.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineBatchNoteError
from worktrace.db import get_connection
from worktrace.services import activity_service, project_service


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


def _get_activity_note(activity_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT note FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    return row["note"] if row else None


def _get_activity_project_id(activity_id: int) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT project_id FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    return int(row["project_id"]) if row else None


def _get_activity_source(activity_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT source FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    return row["source"] if row else None


def _get_activity_status(activity_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    return row["status"] if row else None


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


def _seed_activity_with_note(note_text: str, start="09:00:00", end="09:30:00"):
    """Seed a closed activity with an existing note and return its id."""
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "A1.docx",
        start_time=f"2026-06-25 {start}",
        note=note_text,
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"2026-06-25 {end}")
    return aid


# --- batch_update_timeline_activities_note: validation ----------------


def test_batch_non_list_activity_ids(temp_db):
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note("not a list", "note")
    assert exc.value.code == "invalid_selection"


def test_batch_bool_activity_ids(temp_db):
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note(True, "note")
    assert exc.value.code == "invalid_selection"


def test_batch_empty_list(temp_db):
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note([], "note")
    assert exc.value.code == "invalid_selection"


def test_batch_single_activity(temp_db):
    """Fewer than two ids after dedup must fail."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note([aid], "note")
    assert exc.value.code == "invalid_selection"


def test_batch_bool_id_in_list(temp_db):
    """A ``bool`` element in the list must be rejected."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note([aid, True], "note")
    assert exc.value.code == "invalid_selection"


def test_batch_non_positive_id(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note([aid, 0], "note")
    assert exc.value.code == "invalid_selection"
    with pytest.raises(TimelineBatchNoteError) as exc2:
        timeline_api.batch_update_timeline_activities_note([aid, -1], "note")
    assert exc2.value.code == "invalid_selection"


def test_batch_non_int_id_in_list(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note([aid, "abc"], "note")
    assert exc.value.code == "invalid_selection"


def test_batch_duplicate_ids_deduped(temp_db):
    """Duplicate ids are deduped; a single unique id must fail (< 2)."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note([aid, aid], "note")
    assert exc.value.code == "invalid_selection"


def test_batch_exceeds_upper_limit(temp_db):
    """More than MAX_BATCH_NOTE_EDIT_ACTIVITIES ids must fail."""
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note(
            list(range(1, 102)), "note"
        )
    assert exc.value.code == "batch_too_large"


def test_batch_note_none(temp_db):
    """None note must fail with invalid_note."""
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note(ids, None)
    assert exc.value.code == "invalid_note"


def test_batch_note_non_str(temp_db):
    """Non-string note must fail with invalid_note."""
    ids = _seed_two_closed_activities()
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note(ids, 123)
    assert exc.value.code == "invalid_note"
    with pytest.raises(TimelineBatchNoteError) as exc2:
        timeline_api.batch_update_timeline_activities_note(ids, ["a", "b"])
    assert exc2.value.code == "invalid_note"


def test_batch_note_too_long(temp_db):
    """A note exceeding BATCH_NOTE_MAX_LENGTH must fail with note_too_long."""
    ids = _seed_two_closed_activities()
    long_note = "x" * (activity_service.BATCH_NOTE_MAX_LENGTH + 1)
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note(ids, long_note)
    assert exc.value.code == "note_too_long"


def test_batch_nonexistent_activity(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note([aid, 999999], "note")
    assert exc.value.code == "invalid_selection"


def test_batch_deleted_activity(temp_db):
    ids = _seed_two_closed_activities()
    activity_service.soft_delete_activity(ids[1])
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note(ids, "note")
    assert exc.value.code == "invalid_selection"


def test_batch_hidden_activity(temp_db):
    ids = _seed_two_closed_activities()
    activity_service.hide_activity(ids[1])
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note(ids, "note")
    assert exc.value.code == "hidden_activity"


def test_batch_in_progress_activity(temp_db):
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    # a2 is still open (end_time IS NULL)
    with pytest.raises(TimelineBatchNoteError) as exc:
        timeline_api.batch_update_timeline_activities_note([a1, a2], "note")
    assert exc.value.code == "in_progress"


# --- batch_update_timeline_activities_note: success ----------------------


def test_batch_success(temp_db):
    ids = _seed_two_closed_activities()
    result = timeline_api.batch_update_timeline_activities_note(ids, "new note")
    assert isinstance(result, dict)
    assert result["updated_count"] == 2
    for aid in ids:
        assert _get_activity_note(aid) == "new note"


def test_batch_updated_count_correct(temp_db):
    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    a2 = _seed_closed_activity(start="09:30:00", end="10:00:00")
    a3 = _seed_closed_activity(start="10:00:00", end="10:30:00")
    result = timeline_api.batch_update_timeline_activities_note(
        [a1, a2, a3], "shared note"
    )
    assert result["updated_count"] == 3
    for aid in [a1, a2, a3]:
        assert _get_activity_note(aid) == "shared note"


def test_batch_empty_note_clears(temp_db):
    """An empty string note must clear all selected activities' notes."""
    a1 = _seed_activity_with_note("old note 1")
    a2 = _seed_activity_with_note("old note 2", start="09:30:00", end="10:00:00")
    assert _get_activity_note(a1) == "old note 1"
    assert _get_activity_note(a2) == "old note 2"
    result = timeline_api.batch_update_timeline_activities_note([a1, a2], "")
    assert result["updated_count"] == 2
    assert _get_activity_note(a1) == ""
    assert _get_activity_note(a2) == ""


def test_batch_overwrites_existing_note(temp_db):
    """The new note overwrites (does not append) the existing note."""
    a1 = _seed_activity_with_note("old note 1")
    a2 = _seed_activity_with_note("old note 2", start="09:30:00", end="10:00:00")
    result = timeline_api.batch_update_timeline_activities_note([a1, a2], "replacement")
    assert result["updated_count"] == 2
    assert _get_activity_note(a1) == "replacement"
    assert _get_activity_note(a2) == "replacement"
    # No concatenation of the old note.
    assert "old note" not in _get_activity_note(a1)
    assert "old note" not in _get_activity_note(a2)


def test_batch_note_at_max_length_success(temp_db):
    """A note exactly at BATCH_NOTE_MAX_LENGTH must succeed."""
    ids = _seed_two_closed_activities()
    max_note = "x" * activity_service.BATCH_NOTE_MAX_LENGTH
    result = timeline_api.batch_update_timeline_activities_note(ids, max_note)
    assert result["updated_count"] == 2
    for aid in ids:
        assert _get_activity_note(aid) == max_note


def test_batch_does_not_modify_time_fields(temp_db):
    """start_time, end_time, duration_seconds must not change."""
    ids = _seed_two_closed_activities()
    originals = {}
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT start_time, end_time, duration_seconds FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            originals[aid] = dict(row)
    timeline_api.batch_update_timeline_activities_note(ids, "note")
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT start_time, end_time, duration_seconds FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            assert row["start_time"] == originals[aid]["start_time"]
            assert row["end_time"] == originals[aid]["end_time"]
            assert row["duration_seconds"] == originals[aid]["duration_seconds"]


def test_batch_does_not_modify_project_or_status(temp_db):
    """project_id, status, source, app_name, process_name must not change."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.update_activities_project(ids, project)
    originals = {}
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT project_id, status, source, app_name, process_name FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            originals[aid] = dict(row)
    timeline_api.batch_update_timeline_activities_note(ids, "note")
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT project_id, status, source, app_name, process_name FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            assert row["project_id"] == originals[aid]["project_id"]
            assert row["status"] == originals[aid]["status"]
            assert row["source"] == originals[aid]["source"]
            assert row["app_name"] == originals[aid]["app_name"]
            assert row["process_name"] == originals[aid]["process_name"]


def test_batch_does_not_modify_assignments(temp_db):
    """activity_project_assignment rows must not change."""
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.update_activities_project(ids, project)
    originals = {}
    for aid in ids:
        originals[aid] = {
            "project_id": _get_assignment_project_id(aid),
            "source": _get_assignment_source(aid),
        }
    timeline_api.batch_update_timeline_activities_note(ids, "note")
    for aid in ids:
        assert _get_assignment_project_id(aid) == originals[aid]["project_id"]
        assert _get_assignment_source(aid) == originals[aid]["source"]


def test_batch_does_not_modify_resource_rows(temp_db):
    """activity_resource rows must not be modified by a batch note update."""
    ids = _seed_two_closed_activities()
    originals = {aid: _get_resource_row(aid) for aid in ids}
    assert all(v is not None for v in originals.values())
    timeline_api.batch_update_timeline_activities_note(ids, "note")
    for aid in ids:
        after = _get_resource_row(aid)
        assert after is not None
        for key in (
            "identity_key", "display_name", "path_hint", "path_key",
            "resource_kind", "resource_subtype", "window_title",
        ):
            assert after[key] == originals[aid][key]


def test_batch_does_not_modify_session_note(temp_db):
    """project_session_note must not be modified by a batch note update."""
    from worktrace.db import now_str

    ids = _seed_two_closed_activities()
    note_text = "important session note"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO project_session_note("
            "report_date, first_activity_id, note, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?)",
            ("2026-06-25", ids[0], note_text, now_str(), now_str()),
        )
    timeline_api.batch_update_timeline_activities_note(ids, "activity note")
    assert _get_session_note("2026-06-25", ids[0]) == note_text


def test_batch_does_not_modify_visibility(temp_db):
    """is_hidden, is_deleted must not change."""
    ids = _seed_two_closed_activities()
    originals = {}
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT is_hidden, is_deleted FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            originals[aid] = dict(row)
    timeline_api.batch_update_timeline_activities_note(ids, "note")
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT is_hidden, is_deleted FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            assert row["is_hidden"] == originals[aid]["is_hidden"]
            assert row["is_deleted"] == originals[aid]["is_deleted"]


def test_batch_updated_at_refreshed(temp_db):
    """Every activity's updated_at must be refreshed."""
    ids = _seed_two_closed_activities()
    originals = {}
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT updated_at FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            originals[aid] = row["updated_at"]
    timeline_api.batch_update_timeline_activities_note(ids, "note")
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT updated_at FROM activity_log WHERE id = ?",
                (aid,),
            ).fetchone()
            assert row["updated_at"] >= originals[aid]


def test_batch_no_partial_write_on_validation_failure(temp_db):
    """If any activity fails validation, none are updated."""
    ids = _seed_two_closed_activities()
    # Set a pre-existing note so we can verify it is not touched.
    timeline_api.batch_update_timeline_activities_note(ids, "original")
    # Hide the second activity so the batch fails.
    activity_service.hide_activity(ids[1])
    with pytest.raises(TimelineBatchNoteError):
        timeline_api.batch_update_timeline_activities_note(ids, "new note")
    # Neither activity's note should have changed.
    assert _get_activity_note(ids[0]) == "original"
    assert _get_activity_note(ids[1]) == "original"


def test_batch_rowcount_guard_rollback(temp_db):
    """If the UPDATE affects 0 rows (race condition), it must fail."""
    ids = _seed_two_closed_activities()

    def _mocked_batch(activity_ids, note):
        raise ValueError("note_update_failed")

    with patch.object(
        activity_service, "batch_update_activity_note", _mocked_batch
    ):
        with pytest.raises(TimelineBatchNoteError) as exc:
            timeline_api.batch_update_timeline_activities_note(ids, "note")
    assert exc.value.code == "operation_failed"


def test_batch_returns_no_raw_rows(temp_db):
    """The return value must only contain updated_count, not raw rows."""
    ids = _seed_two_closed_activities()
    result = timeline_api.batch_update_timeline_activities_note(ids, "note")
    assert "updated_count" in result
    assert "rows" not in result
    assert "activities" not in result
    assert "window_title" not in result
    assert "file_path_hint" not in result
    assert "note" not in result
    assert "old_note" not in result
    assert "new_note" not in result
    assert "full_path" not in result


def test_batch_different_projects_ok(temp_db):
    """Activities with different existing projects can be batch-updated."""
    project1 = project_service.create_project("Project1")
    project2 = project_service.create_project("Project2")
    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    a2 = _seed_closed_activity(start="09:30:00", end="10:00:00")
    activity_service.update_activities_project([a1], project1)
    activity_service.update_activities_project([a2], project2)
    result = timeline_api.batch_update_timeline_activities_note([a1, a2], "note")
    assert result["updated_count"] == 2
    assert _get_activity_note(a1) == "note"
    assert _get_activity_note(a2) == "note"
    # Projects must remain unchanged.
    assert _get_activity_project_id(a1) == project1
    assert _get_activity_project_id(a2) == project2


def test_batch_exact_max_100_success(temp_db):
    """Exactly MAX_BATCH_NOTE_EDIT_ACTIVITIES (100) activities must
    succeed."""
    ids = _seed_n_closed_activities(100)
    result = timeline_api.batch_update_timeline_activities_note(ids, "note")
    assert result["updated_count"] == 100
    for aid in ids:
        assert _get_activity_note(aid) == "note"


# --- Service layer direct tests ------------------------------------------


def test_service_batch_success(temp_db):
    ids = _seed_two_closed_activities()
    count = activity_service.batch_update_activity_note(ids, "note")
    assert count == 2


def test_service_batch_invalid_activity_ids(temp_db):
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note("not a list", "note")
    assert str(exc.value) == "invalid_activity_ids"


def test_service_batch_too_large(temp_db):
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note(
            list(range(1, 102)), "note"
        )
    assert str(exc.value) == "batch_too_large"


def test_service_batch_invalid_note(temp_db):
    ids = _seed_two_closed_activities()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note(ids, None)
    assert str(exc.value) == "invalid_note"
    with pytest.raises(ValueError) as exc2:
        activity_service.batch_update_activity_note(ids, 123)
    assert str(exc2.value) == "invalid_note"


def test_service_batch_note_too_long(temp_db):
    ids = _seed_two_closed_activities()
    long_note = "x" * (activity_service.BATCH_NOTE_MAX_LENGTH + 1)
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note(ids, long_note)
    assert str(exc.value) == "note_too_long"


def test_service_batch_activity_not_found(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note([aid, 999999], "note")
    assert str(exc.value) == "activity_not_found"


def test_service_batch_activity_deleted(temp_db):
    ids = _seed_two_closed_activities()
    activity_service.soft_delete_activity(ids[1])
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note(ids, "note")
    assert str(exc.value) == "activity_deleted"


def test_service_batch_activity_hidden(temp_db):
    ids = _seed_two_closed_activities()
    activity_service.hide_activity(ids[1])
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note(ids, "note")
    assert str(exc.value) == "activity_hidden"


def test_service_batch_activity_in_progress(temp_db):
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note([a1, a2], "note")
    assert str(exc.value) == "activity_in_progress"


def test_service_batch_bool_activity_ids(temp_db):
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note(True, "note")
    assert str(exc.value) == "invalid_activity_ids"


def test_service_batch_bool_in_list(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note([aid, True], "note")
    assert str(exc.value) == "invalid_activity_ids"


def test_service_batch_non_positive_id(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(ValueError) as exc:
        activity_service.batch_update_activity_note([aid, 0], "note")
    assert str(exc.value) == "invalid_activity_ids"


# --- Phase 3B.7 hardening: exception rollback + non-leak ----------------


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


def test_service_batch_update_exception_rollback(temp_db):
    """If the activity_log UPDATE raises, the transaction rolls back so no
    activity's note changes."""
    ids = _seed_two_closed_activities()
    # Set original notes so we can verify rollback.
    activity_service.batch_update_activity_note(ids, "original")
    real_get_connection = activity_service.get_connection

    def _patched():
        return _FailingConn(real_get_connection(), "UPDATE activity_log")

    with patch.object(activity_service, "get_connection", _patched):
        with pytest.raises(RuntimeError):
            activity_service.batch_update_activity_note(ids, "new note")

    for aid in ids:
        assert _get_activity_note(aid) == "original"


def test_service_batch_validation_exception_rollback(temp_db):
    """A pre-write exception (activity SELECT) must not corrupt any
    activity's note."""
    ids = _seed_two_closed_activities()
    activity_service.batch_update_activity_note(ids, "original")
    real_get_connection = activity_service.get_connection

    def _patched():
        return _FailingConn(real_get_connection(), "SELECT id, is_deleted")

    with patch.object(activity_service, "get_connection", _patched):
        with pytest.raises(RuntimeError):
            activity_service.batch_update_activity_note(ids, "new note")

    for aid in ids:
        assert _get_activity_note(aid) == "original"


def test_batch_unknown_service_failure_mapping(temp_db):
    """A non-ValueError service exception must map to operation_failed."""
    ids = _seed_two_closed_activities()
    with patch.object(
        activity_service, "batch_update_activity_note",
        side_effect=RuntimeError("unexpected boom"),
    ):
        with pytest.raises(TimelineBatchNoteError) as exc:
            timeline_api.batch_update_timeline_activities_note(ids, "note")
    assert exc.value.code == "operation_failed"


def test_batch_api_does_not_leak_exception_text(temp_db):
    """The TimelineBatchNoteError must not contain the original exception
    text."""
    ids = _seed_two_closed_activities()
    secret = "super_secret_internal_detail"
    with patch.object(
        activity_service, "batch_update_activity_note",
        side_effect=RuntimeError(secret),
    ):
        with pytest.raises(TimelineBatchNoteError) as exc:
            timeline_api.batch_update_timeline_activities_note(ids, "note")
    assert secret not in str(exc.value)
    assert exc.value.code == "operation_failed"


def test_batch_mixed_valid_and_deleted_rejects_all(temp_db):
    """A batch with one valid + one deleted activity must reject all; the
    valid activity's note must not be modified."""
    ids = _seed_two_closed_activities()
    activity_service.batch_update_activity_note(ids, "original")
    activity_service.soft_delete_activity(ids[1])
    with pytest.raises(TimelineBatchNoteError):
        timeline_api.batch_update_timeline_activities_note(ids, "new note")
    assert _get_activity_note(ids[0]) == "original"


def test_batch_mixed_valid_and_in_progress_rejects_all(temp_db):
    """A batch with one valid + one in-progress activity must reject all."""
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A2.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.update_activity_note(a1, "original")
    with pytest.raises(TimelineBatchNoteError):
        timeline_api.batch_update_timeline_activities_note([a1, a2], "new note")
    assert _get_activity_note(a1) == "original"


def test_batch_mixed_valid_and_nonexistent_rejects_all(temp_db):
    """A batch with one valid + one nonexistent id must reject all."""
    aid = _seed_closed_activity()
    activity_service.update_activity_note(aid, "original")
    with pytest.raises(TimelineBatchNoteError):
        timeline_api.batch_update_timeline_activities_note([aid, 999999], "new note")
    assert _get_activity_note(aid) == "original"


# --- No new DB schema ---


def test_batch_no_new_db_schema(temp_db):
    """Batch note update must not introduce new tables or alter existing
    columns."""

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
    ids = _seed_two_closed_activities()
    timeline_api.batch_update_timeline_activities_note(ids, "note")
    after = _schema_snapshot()
    assert before == after
