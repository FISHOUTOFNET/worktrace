"""Tests for the Phase 3A Timeline editing API layer.

Covers ``worktrace.api.timeline_api.reclassify_timeline_session_project``
and ``worktrace.api.timeline_api.update_timeline_session_note``:

- input validation (empty ids, nonexistent ids, invalid project_id,
  invalid date, note length);
- successful writes (project reclassification, note write, whitespace-only
  note deletion);
- multi-activity session consistency;
- re-reading the timeline after a write reflects the change.
"""

from __future__ import annotations

import pytest

from worktrace.api import timeline_api
from worktrace.services import activity_service, project_service


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


def _seed_session(project_id=None):
    """Seed a simple two-activity closed session on 2026-06-25."""
    a1 = _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_id)
    activity_service.close_activity(a1, "2026-06-25 09:10:00")

    a2 = _activity("Word", "winword.exe", "A2.docx", "09:10:00", project_id)
    activity_service.close_activity(a2, "2026-06-25 09:30:00")
    return [a1, a2]


# --- reclassify_timeline_session_project ---------------------------------


def test_reclassify_success(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_session()
    timeline_api.reclassify_timeline_session_project(ids, project)
    # Verify the activities were reclassified
    for aid in ids:
        activity = activity_service.get_activity(aid)
        assert int(activity["project_id"]) == project


def test_reclassify_empty_activity_ids(temp_db):
    project = project_service.create_project("TestProject")
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project([], project)


def test_reclassify_nonexistent_activity_id(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids + [999999], project)


def test_reclassify_invalid_project_id(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids, 0)
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids, -1)


def test_reclassify_nonexistent_project_id(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids, 999999)


def test_reclassify_to_uncategorized(temp_db):
    """Setting to the uncategorized system project should succeed."""
    ids = _seed_session()
    uncat_id = project_service.get_or_create_uncategorized_project()
    timeline_api.reclassify_timeline_session_project(ids, uncat_id)
    for aid in ids:
        activity = activity_service.get_activity(aid)
        assert int(activity["project_id"]) == uncat_id


def test_reclassify_dedupes_activity_ids(temp_db):
    """Duplicate activity_ids should be deduplicated without error."""
    project = project_service.create_project("Dup")
    ids = _seed_session()
    timeline_api.reclassify_timeline_session_project([ids[0], ids[0], ids[1]], project)
    for aid in ids:
        activity = activity_service.get_activity(aid)
        assert int(activity["project_id"]) == project


def test_reclassify_multi_activity_session_consistent(temp_db):
    """All activities in a session must move together to the same project."""
    project = project_service.create_project("Group")
    ids = _seed_session()
    timeline_api.reclassify_timeline_session_project(ids, project)
    project_ids = set()
    for aid in ids:
        activity = activity_service.get_activity(aid)
        project_ids.add(int(activity["project_id"]))
    assert project_ids == {project}


def test_reclassify_then_reread_timeline_reflects_change(temp_db):
    """After reclassification, re-reading the timeline must show the new
    project in the session list."""
    project = project_service.create_project("NewProject")
    ids = _seed_session()
    timeline_api.reclassify_timeline_session_project(ids, project)
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    assert any(s["project_name"] == "NewProject" for s in sessions)


# --- update_timeline_session_note ----------------------------------------


def test_update_note_success(temp_db):
    ids = _seed_session()
    timeline_api.update_timeline_session_note("2026-06-25", ids[0], "test note")
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    # Find the session containing our activities
    note_found = ""
    for s in sessions:
        if ids[0] in (s.get("activity_ids") or []):
            note_found = s.get("session_note") or ""
            break
    assert note_found == "test note"


def test_update_note_preserves_newlines(temp_db):
    """Legitimate newlines inside the note must be preserved."""
    ids = _seed_session()
    note = "line one\nline two"
    timeline_api.update_timeline_session_note("2026-06-25", ids[0], note)
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    for s in sessions:
        if ids[0] in (s.get("activity_ids") or []):
            assert s.get("session_note") == "line one\nline two"
            break


def test_update_note_whitespace_only_deletes(temp_db):
    """A whitespace-only note should delete the existing note row (matching
    legacy set_session_note behavior)."""
    ids = _seed_session()
    # First set a real note
    timeline_api.update_timeline_session_note("2026-06-25", ids[0], "real note")
    # Then overwrite with whitespace-only
    timeline_api.update_timeline_session_note("2026-06-25", ids[0], "   \n  ")
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    for s in sessions:
        if ids[0] in (s.get("activity_ids") or []):
            assert s.get("session_note") == ""
            break


def test_update_note_too_long(temp_db):
    ids = _seed_session()
    long_note = "x" * (timeline_api.TIMELINE_NOTE_MAX_LENGTH + 1)
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note("2026-06-25", ids[0], long_note)


def test_update_note_at_max_length_succeeds(temp_db):
    ids = _seed_session()
    note = "x" * timeline_api.TIMELINE_NOTE_MAX_LENGTH
    timeline_api.update_timeline_session_note("2026-06-25", ids[0], note)
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    for s in sessions:
        if ids[0] in (s.get("activity_ids") or []):
            assert len(s.get("session_note") or "") == timeline_api.TIMELINE_NOTE_MAX_LENGTH
            break


def test_update_note_invalid_date(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note("not-a-date", ids[0], "note")
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note("", ids[0], "note")


def test_update_note_nonexistent_activity(temp_db):
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note("2026-06-25", 999999, "note")


def test_update_note_overwrites_existing(temp_db):
    """Writing a new note should overwrite the previous one (upsert)."""
    ids = _seed_session()
    timeline_api.update_timeline_session_note("2026-06-25", ids[0], "first note")
    timeline_api.update_timeline_session_note("2026-06-25", ids[0], "second note")
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    for s in sessions:
        if ids[0] in (s.get("activity_ids") or []):
            assert s.get("session_note") == "second note"
            break


def test_update_note_non_string_raises(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note("2026-06-25", ids[0], 12345)


# --- update_timeline_session_note_and_duration ---


def test_update_note_and_duration_success(temp_db):
    ids = _seed_session()
    timeline_api.update_timeline_session_note_and_duration(
        "2026-06-25", ids[0], "test note", 3600
    )
    from worktrace.services import session_note_service
    fields = session_note_service.get_session_user_fields("2026-06-25", ids[0])
    assert fields["note"] == "test note"
    assert fields["adjusted_duration_seconds"] == 3600


def test_update_note_and_duration_null_duration_clears_override(temp_db):
    ids = _seed_session()
    # Set override first
    timeline_api.update_timeline_session_note_and_duration(
        "2026-06-25", ids[0], "test", 3600
    )
    # Clear override with None
    timeline_api.update_timeline_session_note_and_duration(
        "2026-06-25", ids[0], "test", None
    )
    from worktrace.services import session_note_service
    fields = session_note_service.get_session_user_fields("2026-06-25", ids[0])
    assert fields["adjusted_duration_seconds"] is None


def test_update_note_and_duration_zero_accepted(temp_db):
    """``0`` is a valid explicit override to zero display/declared duration."""
    ids = _seed_session()
    timeline_api.update_timeline_session_note_and_duration(
        "2026-06-25", ids[0], "note", 0
    )
    from worktrace.services import session_note_service
    fields = session_note_service.get_session_user_fields("2026-06-25", ids[0])
    assert fields["adjusted_duration_seconds"] == 0


def test_update_note_and_duration_negative_rejected(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note_and_duration(
            "2026-06-25", ids[0], "note", -1
        )


def test_update_note_and_duration_bool_rejected(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note_and_duration(
            "2026-06-25", ids[0], "note", True
        )


def test_update_note_and_duration_exceeds_max_rejected(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note_and_duration(
            "2026-06-25", ids[0], "note", timeline_api.TIMELINE_ADJUSTED_DURATION_MAX_SECONDS + 1
        )


def test_update_note_and_duration_invalid_date(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note_and_duration(
            "not-a-date", ids[0], "note", 3600
        )
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note_and_duration(
            "", ids[0], "note", 3600
        )


def test_update_note_and_duration_nonexistent_activity(temp_db):
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note_and_duration(
            "2026-06-25", 999999, "note", 3600
        )


def test_update_note_and_duration_too_long_note(temp_db):
    ids = _seed_session()
    long_note = "x" * (timeline_api.TIMELINE_NOTE_MAX_LENGTH + 1)
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note_and_duration(
            "2026-06-25", ids[0], long_note, 3600
        )


def test_update_note_and_duration_empty_note_with_duration(temp_db):
    """Empty note + duration override should preserve row with duration."""
    ids = _seed_session()
    timeline_api.update_timeline_session_note_and_duration(
        "2026-06-25", ids[0], "", 3600
    )
    from worktrace.services import session_note_service
    fields = session_note_service.get_session_user_fields("2026-06-25", ids[0])
    assert fields["note"] == ""
    assert fields["adjusted_duration_seconds"] == 3600


def test_update_note_only_preserves_existing_duration(temp_db):
    """Set note + duration, then call update_timeline_session_note with a new
    note. The duration override must be preserved."""
    ids = _seed_session()
    # Set both note and duration
    timeline_api.update_timeline_session_note_and_duration(
        "2026-06-25", ids[0], "first note", 3600
    )
    # Update only the note via the note-only API
    timeline_api.update_timeline_session_note("2026-06-25", ids[0], "second note")
    from worktrace.services import session_note_service
    fields = session_note_service.get_session_user_fields("2026-06-25", ids[0])
    assert fields["note"] == "second note"
    assert fields["adjusted_duration_seconds"] == 3600


# --- Phase 3A.1: API input validation hardening --------------------------


def test_reclassify_activity_ids_not_a_list(temp_db):
    """``activity_ids`` must be a list, not a tuple, int, None, or str."""
    project = project_service.create_project("P")
    ids = _seed_session()
    for invalid in (None, "abc", 123, (ids[0],), {"a": 1}):
        with pytest.raises(ValueError):
            timeline_api.reclassify_timeline_session_project(invalid, project)


def test_reclassify_activity_ids_bool_list_rejected(temp_db):
    """``bool`` is a subclass of ``int`` in Python; the API must reject it
    so ``True`` is not coerced to ``1``."""
    project = project_service.create_project("P")
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project([True, False], project)


def test_reclassify_activity_ids_with_bool_element_rejected(temp_db):
    """A ``bool`` element inside an otherwise-valid list must be rejected."""
    project = project_service.create_project("P")
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project([ids[0], True], project)


def test_reclassify_project_id_none_rejected(temp_db):
    """``project_id=None`` must raise, not be treated as 'uncategorized'."""
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids, None)


def test_reclassify_project_id_string_rejected(temp_db):
    """``project_id`` must not accept a string project name."""
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids, "TestProject")


def test_reclassify_project_id_bool_rejected(temp_db):
    """``bool`` must not be coerced to ``1``."""
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids, True)
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids, False)


def test_reclassify_deleted_activity_rejected(temp_db):
    """A soft-deleted activity must fail the validation, not be silently
    skipped."""
    project = project_service.create_project("P")
    ids = _seed_session()
    activity_service.soft_delete_activity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids, project)


def test_update_note_first_activity_id_bool_rejected(temp_db):
    """``bool`` must not be coerced to ``1`` for ``first_activity_id``."""
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note("2026-06-25", True, "note")
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note("2026-06-25", False, "note")


def test_update_note_first_activity_id_deleted_rejected(temp_db):
    """A soft-deleted activity must fail validation for note writing."""
    ids = _seed_session()
    activity_service.soft_delete_activity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note("2026-06-25", ids[0], "note")


def test_reclassify_no_partial_write_on_missing_id(temp_db):
    """When one activity_id is missing, no write must occur. Verify by
    checking the existing activities' project_id is unchanged."""
    project = project_service.create_project("P")
    ids = _seed_session()
    original_project_ids = [
        int(activity_service.get_activity(aid)["project_id"]) for aid in ids
    ]
    with pytest.raises(ValueError):
        timeline_api.reclassify_timeline_session_project(ids + [999999], project)
    # The existing activities must be unchanged.
    for i, aid in enumerate(ids):
        activity = activity_service.get_activity(aid)
        assert int(activity["project_id"]) == original_project_ids[i]
