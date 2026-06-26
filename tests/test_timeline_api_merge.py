"""Tests for the Phase 3B.3 Timeline activity-merge API and service layer.

Covers ``worktrace.api.timeline_api.merge_timeline_activities`` and the
underlying ``worktrace.services.activity_service.merge_activities`` write:

- input validation (non-list, fewer than two, more than two, bool id,
  nonexistent id, deleted activity, in-progress activity, same id duplicated);
- successful merges (two adjacent closed activities, duration recomputation,
  kept activity id preserved, kept start_time unchanged, kept end_time
  extended, later activity soft-deleted, kept created_at unchanged, kept
  updated_at refreshed);
- rejection paths (different project, different resource, different status,
  different source, overlap, gap too large);
- cross-day adjacent activities merge and timeline projection;
- no partial writes on validation failure (both activities unchanged);
- race-condition handling (UPDATE affecting 0 rows rolls back);
- note not concatenated, session note not migrated.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineMergeError
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


def _seed_two_adjacent_activities(
    start1="09:00:00",
    end1="09:30:00",
    start2="09:30:00",
    end2="10:00:00",
    day="2026-06-25",
):
    """Seed two adjacent closed activities and return their ids.

    By default the two activities are perfectly contiguous
    (end1 == start2). The same app/process/window_title/project is used so
    they satisfy all merge preconditions.
    """
    a1 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time=f"{day} {start1}"
    )
    activity_service.finalize_created_activity(a1)
    activity_service.close_activity(a1, f"{day} {end1}")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time=f"{day} {start2}"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, f"{day} {end2}")
    return [a1, a2]


def _count_activities() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()
    return int(row["c"])


def _get_resource_identity(activity_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT identity_key FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return row["identity_key"] if row else None


# --- merge_timeline_activities: validation --------------------------------


def test_merge_non_list_activity_ids(temp_db):
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities("not a list")
    assert exc.value.code == "invalid_selection"


def test_merge_bool_activity_ids(temp_db):
    """``bool`` is a subclass of ``int``; the whole list must be rejected."""
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(True)
    assert exc.value.code == "invalid_selection"


def test_merge_empty_list(temp_db):
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities([])
    assert exc.value.code == "invalid_selection"


def test_merge_single_activity(temp_db):
    """Fewer than two ids after dedup must fail."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities([aid])
    assert exc.value.code == "invalid_selection"


def test_merge_three_activities(temp_db):
    """More than two ids after dedup must fail."""
    ids = _seed_two_adjacent_activities()
    a3 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 10:00:00"
    )
    activity_service.finalize_created_activity(a3)
    activity_service.close_activity(a3, "2026-06-25 10:30:00")
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(ids + [a3])
    assert exc.value.code == "invalid_selection"


def test_merge_bool_id_in_list(temp_db):
    """A ``bool`` element in the list must be rejected."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities([aid, True])
    assert exc.value.code == "invalid_selection"


def test_merge_non_positive_id(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities([aid, 0])
    assert exc.value.code == "invalid_selection"
    with pytest.raises(TimelineMergeError) as exc2:
        timeline_api.merge_timeline_activities([aid, -1])
    assert exc2.value.code == "invalid_selection"


def test_merge_nonexistent_id(temp_db):
    aid = _seed_closed_activity()
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities([aid, 999999])
    assert exc.value.code == "invalid_id"


def test_merge_deleted_activity(temp_db):
    ids = _seed_two_adjacent_activities()
    activity_service.soft_delete_activity(ids[1])
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(ids)
    assert exc.value.code == "invalid_id"


def test_merge_same_id_duplicated(temp_db):
    """Duplicate ids that resolve to one id must fail (need exactly two)."""
    aid = _seed_closed_activity()
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities([aid, aid])
    assert exc.value.code == "invalid_selection"


def test_merge_in_progress_activity(temp_db):
    """An in-progress activity cannot be merged."""
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    # a2 is still open (end_time IS NULL)
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities([a1, a2])
    assert exc.value.code == "in_progress"


# --- merge_timeline_activities: success -----------------------------------


def test_merge_success(temp_db):
    ids = _seed_two_adjacent_activities()
    result = timeline_api.merge_timeline_activities(ids)
    assert result["kept_activity_id"] == ids[0]
    assert result["merged_activity_id"] == ids[1]


def test_merge_kept_is_earlier_activity(temp_db):
    """The kept activity is the earlier one (by start_time, then id)."""
    ids = _seed_two_adjacent_activities()
    result = timeline_api.merge_timeline_activities(ids)
    assert result["kept_activity_id"] == ids[0]
    assert result["merged_activity_id"] == ids[1]


def test_merge_reversed_argument_order_still_correct(temp_db):
    """Passing the ids in reverse order must still keep the earlier one."""
    ids = _seed_two_adjacent_activities()
    result = timeline_api.merge_timeline_activities([ids[1], ids[0]])
    assert result["kept_activity_id"] == ids[0]
    assert result["merged_activity_id"] == ids[1]


def test_merge_kept_start_time_unchanged(temp_db):
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00", start2="09:30:00", end2="10:00:00"
    )
    timeline_api.merge_timeline_activities(ids)
    kept = activity_service.get_activity(ids[0])
    assert kept["start_time"] == "2026-06-25 09:00:00"


def test_merge_kept_end_time_extended(temp_db):
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00", start2="09:30:00", end2="10:00:00"
    )
    timeline_api.merge_timeline_activities(ids)
    kept = activity_service.get_activity(ids[0])
    assert kept["end_time"] == "2026-06-25 10:00:00"


def test_merge_duration_precisely_recomputed(temp_db):
    """The kept activity's duration_seconds must exactly equal the merged
    range (later.end_time - earlier.start_time) in seconds."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00", start2="09:30:00", end2="10:00:00"
    )
    # Original durations: 30 min each = 1800 seconds each.
    before1 = activity_service.get_activity(ids[0])
    before2 = activity_service.get_activity(ids[1])
    assert int(before1["duration_seconds"]) == 1800
    assert int(before2["duration_seconds"]) == 1800
    timeline_api.merge_timeline_activities(ids)
    kept = activity_service.get_activity(ids[0])
    # Merged range: 09:00 - 10:00 = 3600 seconds.
    assert int(kept["duration_seconds"]) == 3600


def test_merge_later_activity_soft_deleted(temp_db):
    """The later activity must be soft-deleted (is_deleted = 1), not
    physically removed."""
    ids = _seed_two_adjacent_activities()
    before_count = _count_activities()
    timeline_api.merge_timeline_activities(ids)
    # The later activity row still exists in the DB (soft-delete).
    after_count = _count_activities()
    assert after_count == before_count
    merged = activity_service.get_activity(ids[1])
    # get_activity does not filter by is_deleted, so the row is still
    # returned. Verify the is_deleted flag is set.
    assert merged is not None
    assert int(merged.get("is_deleted") or 0) == 1
    # Verify the row still exists with is_deleted = 1 in a raw query.
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_deleted FROM activity_log WHERE id = ?",
            (ids[1],),
        ).fetchone()
    assert int(row["is_deleted"]) == 1


def test_merge_kept_created_at_unchanged(temp_db):
    """The kept activity's created_at must not change."""
    ids = _seed_two_adjacent_activities()
    before = activity_service.get_activity(ids[0])
    orig_created = before["created_at"]
    timeline_api.merge_timeline_activities(ids)
    kept = activity_service.get_activity(ids[0])
    assert kept["created_at"] == orig_created


def test_merge_kept_updated_at_refreshed(temp_db):
    """The kept activity's updated_at must be refreshed to the write time."""
    ids = _seed_two_adjacent_activities()
    before = activity_service.get_activity(ids[0])
    orig_updated = before["updated_at"]
    timeline_api.merge_timeline_activities(ids)
    kept = activity_service.get_activity(ids[0])
    assert kept["updated_at"] >= orig_updated


def test_merge_within_gap_tolerance(temp_db):
    """A small gap (<= MERGE_GAP_TOLERANCE_SECONDS) must be allowed."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00",
        start2="09:30:02", end2="10:00:00",
    )
    # 2-second gap is within tolerance.
    result = timeline_api.merge_timeline_activities(ids)
    assert result["kept_activity_id"] == ids[0]


# --- merge_timeline_activities: rejection paths ---------------------------


def test_merge_different_project_rejected(temp_db):
    ids = _seed_two_adjacent_activities()
    from worktrace.services import project_service

    project = project_service.create_project("OtherProj")
    activity_service.update_activity_project(ids[1], project, manual=True)
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(ids)
    assert exc.value.code == "different_project"


def test_merge_different_resource_rejected(temp_db):
    """Two activities with different resource identity_keys must be rejected."""
    ids = _seed_two_adjacent_activities()
    # The two activities have the same window_title "A1.docx" so their
    # resources match. Change the second activity's resource identity by
    # updating its activity_resource row directly.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_resource SET identity_key = ? WHERE activity_id = ?",
            ("different_identity_key", ids[1]),
        )
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(ids)
    assert exc.value.code == "different_resource"


def test_merge_different_status_rejected(temp_db):
    """Two activities with different status must be rejected."""
    ids = _seed_two_adjacent_activities()
    # Change the second activity's status to 'idle'.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET status = 'idle' WHERE id = ?",
            (ids[1],),
        )
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(ids)
    assert exc.value.code == "incompatible_activity"


def test_merge_different_source_rejected(temp_db):
    """Two activities with different source must be rejected."""
    ids = _seed_two_adjacent_activities()
    # Change the second activity's source to 'manual'.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET source = 'manual' WHERE id = ?",
            (ids[1],),
        )
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(ids)
    assert exc.value.code == "incompatible_activity"


def test_merge_overlap_rejected(temp_db):
    """Two overlapping activities must be rejected with invalid_time."""
    # first: 09:00-09:30, second: 09:20-10:00 (overlap).
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00",
        start2="09:20:00", end2="10:00:00",
    )
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(ids)
    assert exc.value.code == "invalid_time"


def test_merge_gap_too_large_rejected(temp_db):
    """A gap larger than MERGE_GAP_TOLERANCE_SECONDS must be rejected."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00",
        start2="10:00:00", end2="10:30:00",
    )
    # 30-minute gap is way beyond the 2-second tolerance.
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities(ids)
    assert exc.value.code == "not_adjacent"


# --- Cross-day merge ------------------------------------------------------


def test_merge_cross_day_adjacent_activities(temp_db):
    """Two adjacent activities spanning midnight must merge and project
    correctly via timeline_service."""
    a1 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 23:30:00"
    )
    activity_service.finalize_created_activity(a1)
    activity_service.close_activity(a1, "2026-06-26 00:00:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-26 00:00:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, "2026-06-26 00:30:00")
    result = timeline_api.merge_timeline_activities([a1, a2])
    assert result["kept_activity_id"] == a1
    kept = activity_service.get_activity(a1)
    assert kept["start_time"] == "2026-06-25 23:30:00"
    assert kept["end_time"] == "2026-06-26 00:30:00"
    # The merged activity should appear on 2026-06-25 (cross-day projection
    # by timeline_service).
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    found = any(a1 in (s.get("activity_ids") or []) for s in sessions)
    assert found, "merged activity must appear on 2026-06-25 via projection"


# --- No partial writes ----------------------------------------------------


def test_merge_no_partial_write_on_validation_failure(temp_db):
    """If validation fails, both activities must be untouched."""
    ids = _seed_two_adjacent_activities()
    originals = {aid: activity_service.get_activity(aid) for aid in ids}
    before_count = _count_activities()
    # Different project will fail.
    from worktrace.services import project_service

    project = project_service.create_project("OtherProj")
    activity_service.update_activity_project(ids[1], project, manual=True)
    with pytest.raises(TimelineMergeError):
        timeline_api.merge_timeline_activities(ids)
    for aid in ids:
        after = activity_service.get_activity(aid)
        if after is None:
            # The second activity was not deleted by the failed merge
            # attempt (it may have been the one with the different project,
            # but it should still be non-deleted).
            continue
        assert after["start_time"] == originals[aid]["start_time"]
        assert after["end_time"] == originals[aid]["end_time"]
    assert _count_activities() == before_count


def test_merge_no_partial_write_on_overlap(temp_db):
    """Overlap rejection must not modify either activity."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00",
        start2="09:20:00", end2="10:00:00",
    )
    originals = {aid: activity_service.get_activity(aid) for aid in ids}
    with pytest.raises(TimelineMergeError):
        timeline_api.merge_timeline_activities(ids)
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert after["start_time"] == originals[aid]["start_time"]
        assert after["end_time"] == originals[aid]["end_time"]


# --- Note / session note semantics ----------------------------------------


def test_merge_note_not_concatenated(temp_db):
    """The kept activity's note must be preserved; the later activity's
    note must NOT be copied or concatenated."""
    a1 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx",
        start_time="2026-06-25 09:00:00",
        note="first note",
    )
    activity_service.finalize_created_activity(a1)
    activity_service.close_activity(a1, "2026-06-25 09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx",
        start_time="2026-06-25 09:30:00",
        note="second note",
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, "2026-06-25 10:00:00")
    timeline_api.merge_timeline_activities([a1, a2])
    kept = activity_service.get_activity(a1)
    assert kept.get("note") == "first note"


def test_merge_session_note_not_migrated(temp_db):
    """project_session_note keyed to the later activity's id must NOT be
    migrated to the kept activity. The note row remains keyed to the
    (now-deleted) later activity id; the kept activity does not inherit
    a session note from the merged activity."""
    ids = _seed_two_adjacent_activities()
    # Write a session note keyed to the LATER activity's id.
    timeline_api.update_timeline_session_note("2026-06-25", ids[1], "later note")
    timeline_api.merge_timeline_activities(ids)
    # The session note keyed to the later (now deleted) activity still
    # exists in the DB (we don't migrate or delete it).
    with get_connection() as conn:
        later_row = conn.execute(
            "SELECT note FROM project_session_note "
            "WHERE report_date = ? AND first_activity_id = ?",
            ("2026-06-25", ids[1]),
        ).fetchone()
    assert later_row is not None
    assert later_row["note"] == "later note"
    # No session note was auto-created for the kept activity.
    with get_connection() as conn:
        kept_row = conn.execute(
            "SELECT note FROM project_session_note "
            "WHERE report_date = ? AND first_activity_id = ?",
            ("2026-06-25", ids[0]),
        ).fetchone()
    assert kept_row is None


# --- Race condition -------------------------------------------------------


def test_merge_race_condition_returns_operation_failed(temp_db):
    """If the service-layer UPDATE affects 0 rows (race condition: the
    activity was deleted or re-opened between the service's SELECT and
    UPDATE), the service raises
    ``ValueError("activity_merge_update_affected_zero_rows")`` and the
    API must map it to ``TimelineMergeError("operation_failed")``."""
    ids = _seed_two_adjacent_activities()
    # Mock the service to raise the race-condition error directly. This
    # simulates the UPDATE WHERE clause matching 0 rows without actually
    # modifying the DB (which would be caught by the service's own SELECT
    # before reaching the UPDATE).
    with patch.object(
        activity_service,
        "merge_activities",
        side_effect=ValueError("activity_merge_update_affected_zero_rows"),
    ):
        with pytest.raises(TimelineMergeError) as exc:
            timeline_api.merge_timeline_activities(ids)
    assert exc.value.code == "operation_failed"


# --- Service-layer direct tests ------------------------------------------


def test_service_merge_same_id_raises(temp_db):
    """The service layer must raise ValueError when both ids are the same."""
    aid = _seed_closed_activity()
    with pytest.raises(ValueError):
        activity_service.merge_activities(aid, aid)


def test_service_merge_nonexistent_raises(temp_db):
    """The service layer must raise ValueError when an id does not exist."""
    aid = _seed_closed_activity()
    with pytest.raises(ValueError):
        activity_service.merge_activities(aid, 999999)


def test_service_merge_deleted_raises(temp_db):
    """The service layer must raise ValueError when an activity is deleted."""
    ids = _seed_two_adjacent_activities()
    activity_service.soft_delete_activity(ids[1])
    with pytest.raises(ValueError):
        activity_service.merge_activities(ids[0], ids[1])


def test_service_merge_in_progress_raises(temp_db):
    """The service layer must raise ValueError when an activity is open."""
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    with pytest.raises(ValueError):
        activity_service.merge_activities(a1, a2)


def test_service_merge_kept_update_zero_rowcount_rolls_back(temp_db):
    """If the UPDATE on the kept activity affects 0 rows (race condition),
    the service must raise ValueError and the later activity must NOT be
    soft-deleted."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00", start2="09:30:00", end2="10:00:00"
    )
    real_get_connection = activity_service.get_connection

    class _ZeroRowCursor:
        def __init__(self, real_cursor):
            self._real = real_cursor

        @property
        def rowcount(self):
            return 0

        def __getattr__(self, name):
            return getattr(self._real, name)

    class _ZeroRowUpdateConn:
        """Wraps a real connection. The first UPDATE activity_log (the
        kept-activity end_time update) returns a _ZeroRowCursor so the
        guard fires. All other statements delegate."""

        def __init__(self, real):
            self._real = real
            self._kept_update_seen = False

        def execute(self, sql, params=()):
            stripped = " ".join(sql.split())
            if (
                "UPDATE activity_log" in stripped
                and "SET end_time =" in stripped
                and "duration_seconds =" in stripped
                and not self._kept_update_seen
            ):
                self._kept_update_seen = True
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
            activity_service.merge_activities(ids[0], ids[1])
    # The later activity must NOT have been soft-deleted (the transaction
    # rolled back when the kept UPDATE reported 0 rows).
    later = activity_service.get_activity(ids[1])
    assert later is not None
    assert int(later.get("is_deleted") or 0) == 0


def test_service_merge_soft_delete_zero_rowcount_rolls_back(temp_db):
    """If the soft-delete UPDATE on the later activity affects 0 rows (race
    condition), the service must raise ValueError and the kept activity's
    end_time must be restored (rolled back)."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00", start2="09:30:00", end2="10:00:00"
    )
    orig_kept_end = activity_service.get_activity(ids[0])["end_time"]
    real_get_connection = activity_service.get_connection

    class _ZeroRowCursor:
        def __init__(self, real_cursor):
            self._real = real_cursor

        @property
        def rowcount(self):
            return 0

        def __getattr__(self, name):
            return getattr(self._real, name)

    class _ZeroRowSoftDeleteConn:
        """Wraps a real connection. The UPDATE activity_log with
        ``SET is_deleted = 1`` (the soft-delete) returns a _ZeroRowCursor
        so the guard fires. The kept-activity UPDATE runs normally."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, params=()):
            stripped = " ".join(sql.split())
            if "UPDATE activity_log" in stripped and "SET is_deleted = 1" in stripped:
                cur = self._real.execute(sql, params)
                return _ZeroRowCursor(cur)
            return self._real.execute(sql, params)

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    def patched_get_connection():
        return _ZeroRowSoftDeleteConn(real_get_connection())

    with patch.object(
        activity_service, "get_connection", side_effect=patched_get_connection
    ):
        with pytest.raises(ValueError):
            activity_service.merge_activities(ids[0], ids[1])
    # The kept activity's end_time must have been rolled back.
    kept = activity_service.get_activity(ids[0])
    assert kept["end_time"] == orig_kept_end
    # The later activity must NOT have been soft-deleted.
    later = activity_service.get_activity(ids[1])
    assert later is not None
    assert int(later.get("is_deleted") or 0) == 0


def test_service_merge_assignment_resource_not_complex_merged(temp_db):
    """The kept activity's assignment and resource rows are preserved; the
    later activity's rows are left in place (not physically deleted). The
    merge does NOT create new assignment/resource rows on the kept
    activity."""
    from worktrace.services import project_service

    project = project_service.create_project("MergeProj")
    ids = _seed_two_adjacent_activities()
    activity_service.update_activity_project(ids[0], project, manual=True)
    activity_service.update_activity_project(ids[1], project, manual=True)
    # Count assignment and resource rows before merge.
    with get_connection() as conn:
        before_assignments = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_project_assignment "
            "WHERE activity_id IN (?, ?)",
            (ids[0], ids[1]),
        ).fetchone()["c"]
        before_resources = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_resource "
            "WHERE activity_id IN (?, ?)",
            (ids[0], ids[1]),
        ).fetchone()["c"]
    timeline_api.merge_timeline_activities(ids)
    # After merge, the same number of assignment and resource rows should
    # exist (the later activity's rows are NOT deleted).
    with get_connection() as conn:
        after_assignments = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_project_assignment "
            "WHERE activity_id IN (?, ?)",
            (ids[0], ids[1]),
        ).fetchone()["c"]
        after_resources = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_resource "
            "WHERE activity_id IN (?, ?)",
            (ids[0], ids[1]),
        ).fetchone()["c"]
    assert after_assignments == before_assignments
    assert after_resources == before_resources


# --- Phase 3B.3.1: merge hardening tests ----------------------------------
#
# These tests cover the hardening edge cases the Phase 3B.3 foundation
# tests did not explicitly exercise: excluded vs non-excluded rejection,
# no-partial-write for every rejection path, kept-fields-unchanged on
# validation failure, soft-delete UPDATE exception rollback, and the
# full service-ValueError → API-error-code mapping table.


def test_merge_excluded_vs_non_excluded_rejected(temp_db):
    """Excluded vs non-excluded activities must be rejected.

    Excluded activities are always anonymised to the ``system:excluded``
    resource identity (see ``resource_service._enforce_anonymous_if_excluded``
    and ``make_system_resource``), which differs from a normal activity's
    file-based identity_key. The service checks resource identity before
    status, so this case is rejected with ``different_resource`` — a
    stronger and earlier guard that also covers the excluded-vs-non-excluded
    boundary without needing a separate status check.
    """
    from worktrace.constants import STATUS_EXCLUDED

    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx",
        start_time="2026-06-25 09:30:00",
        status=STATUS_EXCLUDED,
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, "2026-06-25 10:00:00")
    with pytest.raises(TimelineMergeError) as exc:
        timeline_api.merge_timeline_activities([a1, a2])
    assert exc.value.code == "different_resource"


def test_merge_no_partial_write_on_different_resource(temp_db):
    """Different resource must not modify either activity."""
    ids = _seed_two_adjacent_activities()
    originals = {aid: activity_service.get_activity(aid) for aid in ids}
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_resource SET identity_key = ? WHERE activity_id = ?",
            ("different_identity_key", ids[1]),
        )
    with pytest.raises(TimelineMergeError):
        timeline_api.merge_timeline_activities(ids)
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert after["start_time"] == originals[aid]["start_time"]
        assert after["end_time"] == originals[aid]["end_time"]
        assert int(after["is_deleted"] or 0) == 0


def test_merge_no_partial_write_on_different_status(temp_db):
    """Different status must not modify either activity."""
    ids = _seed_two_adjacent_activities()
    originals = {aid: activity_service.get_activity(aid) for aid in ids}
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET status = 'idle' WHERE id = ?",
            (ids[1],),
        )
    with pytest.raises(TimelineMergeError):
        timeline_api.merge_timeline_activities(ids)
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert after["start_time"] == originals[aid]["start_time"]
        assert after["end_time"] == originals[aid]["end_time"]
        assert int(after["is_deleted"] or 0) == 0


def test_merge_no_partial_write_on_different_source(temp_db):
    """Different source must not modify either activity."""
    ids = _seed_two_adjacent_activities()
    originals = {aid: activity_service.get_activity(aid) for aid in ids}
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET source = 'manual' WHERE id = ?",
            (ids[1],),
        )
    with pytest.raises(TimelineMergeError):
        timeline_api.merge_timeline_activities(ids)
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert after["start_time"] == originals[aid]["start_time"]
        assert after["end_time"] == originals[aid]["end_time"]
        assert int(after["is_deleted"] or 0) == 0


def test_merge_no_partial_write_on_gap_too_large(temp_db):
    """Gap too large must not modify either activity."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00",
        start2="10:00:00", end2="10:30:00",
    )
    originals = {aid: activity_service.get_activity(aid) for aid in ids}
    with pytest.raises(TimelineMergeError):
        timeline_api.merge_timeline_activities(ids)
    for aid in ids:
        after = activity_service.get_activity(aid)
        assert after["start_time"] == originals[aid]["start_time"]
        assert after["end_time"] == originals[aid]["end_time"]
        assert int(after["is_deleted"] or 0) == 0


def test_merge_kept_fields_unchanged_on_validation_failure(temp_db):
    """On any validation failure, the kept activity's start_time,
    end_time, duration_seconds, and updated_at must all be unchanged."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00", start2="09:30:00", end2="10:00:00"
    )
    kept_before = activity_service.get_activity(ids[0])
    # Trigger a validation failure (different project).
    from worktrace.services import project_service

    project = project_service.create_project("Blocker")
    activity_service.update_activity_project(ids[1], project, manual=True)
    with pytest.raises(TimelineMergeError):
        timeline_api.merge_timeline_activities(ids)
    kept_after = activity_service.get_activity(ids[0])
    assert kept_after["start_time"] == kept_before["start_time"]
    assert kept_after["end_time"] == kept_before["end_time"]
    assert int(kept_after["duration_seconds"] or 0) == int(
        kept_before["duration_seconds"] or 0
    )
    assert kept_after["updated_at"] == kept_before["updated_at"]


def test_service_merge_soft_delete_exception_rolls_back(temp_db):
    """If the soft-delete UPDATE raises an exception (not just rowcount 0),
    the exception propagates and the ``with get_connection()`` context
    manager rolls back the transaction so the kept activity's end_time
    returns to its original value and the later activity is NOT soft-deleted.

    The service does not wrap the soft-delete UPDATE in its own try/except;
    it relies on the sqlite3 connection context manager for rollback. This
    test simulates a mid-transaction database failure and verifies that no
    partial write survives.
    """
    import sqlite3

    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00", start2="09:30:00", end2="10:00:00"
    )
    orig_kept_end = activity_service.get_activity(ids[0])["end_time"]
    real_get_connection = activity_service.get_connection

    class _ExplodingSoftDeleteConn:
        """Wraps a real connection. The soft-delete UPDATE (SET is_deleted = 1)
        raises a sqlite3.Error to simulate a database failure mid-transaction.
        All other statements delegate to the real connection."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, params=()):
            stripped = " ".join(sql.split())
            if "UPDATE activity_log" in stripped and "SET is_deleted = 1" in stripped:
                raise sqlite3.OperationalError("simulated soft-delete failure")
            return self._real.execute(sql, params)

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    def patched_get_connection():
        return _ExplodingSoftDeleteConn(real_get_connection())

    with patch.object(
        activity_service, "get_connection", side_effect=patched_get_connection
    ):
        # The sqlite3.OperationalError propagates out of merge_activities;
        # the connection context manager rolls back the transaction.
        with pytest.raises(sqlite3.OperationalError):
            activity_service.merge_activities(ids[0], ids[1])
    # The kept activity's end_time must have been rolled back.
    kept = activity_service.get_activity(ids[0])
    assert kept["end_time"] == orig_kept_end
    # The later activity must NOT have been soft-deleted.
    later = activity_service.get_activity(ids[1])
    assert later is not None
    assert int(later.get("is_deleted") or 0) == 0


def test_api_maps_all_service_value_error_codes(temp_db):
    """Every service-layer ValueError code used by ``merge_activities`` must
    map to a stable ``TimelineMergeError`` code. This is a table-driven test
    that exercises the mapping in ``merge_timeline_activities`` directly by
    mocking the service to raise each known code."""
    code_map = {
        "activity_merge_same_id": "invalid_selection",
        "activity_merge_not_found_or_deleted": "invalid_id",
        "activity_merge_in_progress": "in_progress",
        "activity_merge_overlap": "invalid_time",
        "activity_merge_not_adjacent": "not_adjacent",
        "activity_merge_different_project": "different_project",
        "activity_merge_different_resource": "different_resource",
        "activity_merge_incompatible_activity": "incompatible_activity",
        "activity_merge_update_affected_zero_rows": "operation_failed",
        "some_unknown_code": "operation_failed",
    }
    ids = _seed_two_adjacent_activities()
    for service_code, expected_api_code in code_map.items():
        with patch.object(
            activity_service,
            "merge_activities",
            side_effect=ValueError(service_code),
        ):
            with pytest.raises(TimelineMergeError) as exc:
                timeline_api.merge_timeline_activities(ids)
        assert exc.value.code == expected_api_code, (
            f"service code {service_code!r} must map to "
            f"{expected_api_code!r}, got {exc.value.code!r}"
        )
