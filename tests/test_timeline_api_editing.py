"""Tests for the Timeline editing API layer.

Covers ``worktrace.api.timeline_api.save_timeline_session_override``,
``update_timeline_session_note``, and ``update_timeline_session_note_and_duration``
under the Session Edit Contract:

- exact session identity (report_date + activity_ids + activity_member_hash);
- input validation (empty ids, nonexistent ids, invalid project_id,
  invalid date, note length, duration bounds, bool rejection);
- successful writes (project override, note, duration, combined);
- multi-activity session consistency;
- re-reading the timeline after a write reflects the change;
- legacy first-activity forms are disabled.
"""

from __future__ import annotations

import pytest

from worktrace.api import timeline_api
from worktrace.db import get_connection
from worktrace.services import activity_service, project_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


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


def _seed_closed_status_activity(status="idle", project_id=None):
    aid = _activity(status.title(), status, f"{status} status", "09:00:00", project_id, status=status)
    activity_service.close_activity(aid, "2026-06-25 09:10:00")
    return aid


def _session_note_count(first_activity_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM report_session_operation o
            JOIN report_session_operation_member m ON m.operation_id = o.id
            WHERE o.operation_type = 'edit_session'
              AND m.activity_id = ?
            """,
            (first_activity_id,),
        ).fetchone()
    return int(row["c"] or 0)


def _session_for(activity_id: int) -> dict:
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    for session in sessions:
        if activity_id in (session.get("activity_ids") or []):
            return session
    raise AssertionError("session not found")


def _session_user_fields(activity_id: int) -> dict:
    session = _session_for(activity_id)
    return {
        "note": session.get("session_note") or "",
        "adjusted_duration_seconds": session.get("adjusted_duration_seconds"),
    }


def _session_identity(activity_id: int) -> tuple:
    session = _session_for(activity_id)
    return (session["activity_ids"], session["activity_member_hash"])


# ---------------------------------------------------------------------------
# Success tests
# ---------------------------------------------------------------------------


def test_save_override_project_success(temp_db):
    project = project_service.create_project("TestProject")
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, project, None, ""
    )
    assert int(_session_for(ids[0])["project_id"]) == project


def test_save_override_note_success(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, "test note"
    )
    fields = _session_user_fields(ids[0])
    assert fields["note"] == "test note"


def test_save_override_duration_success(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, 3600, ""
    )
    fields = _session_user_fields(ids[0])
    assert fields["adjusted_duration_seconds"] == 3600


def test_save_override_all_three(temp_db):
    project = project_service.create_project("AllThree")
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, project, 3600, "combined note"
    )
    session = _session_for(ids[0])
    assert int(session["project_id"]) == project
    assert session.get("session_note") == "combined note"
    assert session.get("adjusted_duration_seconds") == 3600


def test_save_override_to_uncategorized(temp_db):
    """Setting to the uncategorized system project should succeed."""
    ids = _seed_session()
    uncat_id = project_service.get_or_create_uncategorized_project()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, uncat_id, None, ""
    )
    assert int(_session_for(ids[0])["project_id"]) == uncat_id


def test_save_override_dedupes_activity_ids(temp_db):
    """Duplicate activity_ids should be deduplicated without error."""
    project = project_service.create_project("Dup")
    ids = _seed_session()
    _, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", [ids[0], ids[0], ids[1]], member_hash, project, None, ""
    )
    assert int(_session_for(ids[0])["project_id"]) == project


def test_save_override_multi_activity_session_consistent(temp_db):
    """All activities in a session must move together to the same project."""
    project = project_service.create_project("Group")
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, project, None, ""
    )
    session = _session_for(ids[0])
    assert int(session["project_id"]) == project
    for aid in session["activity_ids"]:
        assert int(_session_for(aid)["project_id"]) == project


def test_save_override_then_reread_timeline_reflects_change(temp_db):
    """After saving an override, re-reading the timeline must show the new
    project in the session list."""
    project = project_service.create_project("NewProject")
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, project, None, ""
    )
    sessions = timeline_api.get_project_sessions_by_date(
        "2026-06-25", include_hidden=False, ensure_context=True
    )
    assert any(s["project_name"] == "NewProject" for s in sessions)


def test_save_override_preserves_newlines(temp_db):
    """Legitimate newlines inside the note must be preserved."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    note = "line one\nline two"
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, note
    )
    fields = _session_user_fields(ids[0])
    assert fields["note"] == "line one\nline two"


def test_save_override_whitespace_note_clears(temp_db):
    """A whitespace-only note should clear the existing note (matching
    set_session_note behavior)."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, "real note"
    )
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, "   \n  "
    )
    fields = _session_user_fields(ids[0])
    assert fields["note"] == ""


def test_save_override_note_at_max_length(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    note = "x" * timeline_api.TIMELINE_NOTE_MAX_LENGTH
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, note
    )
    fields = _session_user_fields(ids[0])
    assert len(fields["note"]) == timeline_api.TIMELINE_NOTE_MAX_LENGTH


def test_save_override_overwrites_existing(temp_db):
    """Writing a new override should overwrite the previous one (upsert)."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, "first note"
    )
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, "second note"
    )
    fields = _session_user_fields(ids[0])
    assert fields["note"] == "second note"


def test_save_override_duration_zero_accepted(temp_db):
    """``0`` is a valid explicit override to zero display/declared duration."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, 0, ""
    )
    fields = _session_user_fields(ids[0])
    assert fields["adjusted_duration_seconds"] == 0


def test_save_override_null_duration_clears_override(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, 3600, ""
    )
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, ""
    )
    fields = _session_user_fields(ids[0])
    assert fields["adjusted_duration_seconds"] is None


def test_save_override_empty_note_preserves_duration(temp_db):
    """Empty note + duration override should preserve row with duration."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, 3600, ""
    )
    fields = _session_user_fields(ids[0])
    assert fields["note"] == ""
    assert fields["adjusted_duration_seconds"] == 3600


def test_save_override_note_only_preserves_duration(temp_db):
    """Set note + duration, then call update_timeline_session_note with a new
    note. The duration override must be preserved."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, 3600, "first note"
    )
    timeline_api.update_timeline_session_note(
        "2026-06-25", activity_ids, member_hash, "second note"
    )
    fields = _session_user_fields(ids[0])
    assert fields["note"] == "second note"
    assert fields["adjusted_duration_seconds"] == 3600


def test_save_override_note_and_duration_together(temp_db):
    """update_timeline_session_note_and_duration with exact identity."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.update_timeline_session_note_and_duration(
        "2026-06-25", activity_ids, member_hash, "test note", 3600
    )
    fields = _session_user_fields(ids[0])
    assert fields["note"] == "test note"
    assert fields["adjusted_duration_seconds"] == 3600


def test_save_override_empty_note_and_null_duration_appends_inherit_command(temp_db):
    """Empty note + None duration clears final fields without deleting history."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, 3600, "note"
    )
    assert _session_note_count(ids[0]) == 1
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, ""
    )
    fields = _session_user_fields(ids[0])
    assert fields["note"] == ""
    assert fields["adjusted_duration_seconds"] is None
    assert _session_note_count(ids[0]) == 2


def test_save_override_system_status_activity_rejected_without_partial_write(temp_db):
    target_project = project_service.create_project("Target")
    aid = _seed_closed_status_activity(status="idle")

    with pytest.raises(ValueError, match="not_project_activity"):
        timeline_api.save_timeline_session_override(
            "2026-06-25", [aid], "0" * 40, target_project, None, ""
        )

    assert _session_note_count(aid) == 0


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------


def test_save_override_empty_activity_ids(temp_db):
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", [], "0" * 40, None, None, ""
        )


def test_save_override_nonexistent_activity_id(temp_db):
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", [999999], "0" * 40, None, None, ""
        )


def test_save_override_invalid_project_id(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, 0, None, ""
        )
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, -1, None, ""
        )


def test_save_override_nonexistent_project_id(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, 999999, None, ""
        )


def test_save_override_invalid_date(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "not-a-date", activity_ids, member_hash, None, None, ""
        )
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "", activity_ids, member_hash, None, None, ""
        )


def test_save_override_too_long_note(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    long_note = "x" * (timeline_api.TIMELINE_NOTE_MAX_LENGTH + 1)
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, None, None, long_note
        )


def test_save_override_negative_duration(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, None, -1, ""
        )


def test_save_override_bool_duration(temp_db):
    """``bool`` is a subclass of ``int`` in Python; the API must reject it
    so ``True`` is not coerced to ``1``."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, None, True, ""
        )
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, None, False, ""
        )


def test_save_override_exceeds_max_duration(temp_db):
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25",
            activity_ids,
            member_hash,
            None,
            timeline_api.TIMELINE_ADJUSTED_DURATION_MAX_SECONDS + 1,
            "",
        )


def test_save_override_activity_ids_not_a_list(temp_db):
    """``activity_ids`` must be a list, not a tuple, int, None, or str."""
    ids = _seed_session()
    for invalid in (None, "abc", 123, (ids[0],), {"a": 1}):
        with pytest.raises(ValueError):
            timeline_api.save_timeline_session_override(
                "2026-06-25", invalid, "0" * 40, None, None, ""
            )


def test_save_override_bool_activity_id_element(temp_db):
    """``bool`` is a subclass of ``int`` in Python; the API must reject it
    so ``True`` is not coerced to ``1``."""
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", [True, False], "0" * 40, None, None, ""
        )


def test_save_override_deleted_activity_rejected(temp_db):
    """A soft-deleted activity must fail the validation, not be silently
    skipped."""
    project = project_service.create_project("P")
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    with get_connection() as conn:
        conn.execute("UPDATE activity_log SET is_deleted = 1 WHERE id = ?", (ids[0],))
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, project, None, ""
        )


def test_save_override_no_partial_write_on_missing_id(temp_db):
    """When one activity_id is missing, no write must occur. Verify by
    checking the existing activities' project_id is unchanged and no
    override row is written."""
    project = project_service.create_project("P")
    ids = _seed_session()
    _, member_hash = _session_identity(ids[0])
    original_project_ids = []
    with get_connection() as conn:
        for aid in ids:
            row = conn.execute(
                "SELECT project_id FROM activity_log WHERE id = ?", (aid,)
            ).fetchone()
            original_project_ids.append(row["project_id"])
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", [ids[0], 999999], member_hash, project, None, ""
        )
    with get_connection() as conn:
        for i, aid in enumerate(ids):
            row = conn.execute(
                "SELECT project_id FROM activity_log WHERE id = ?", (aid,)
            ).fetchone()
            assert row["project_id"] == original_project_ids[i]
    assert _session_note_count(ids[0]) == 0


def test_save_override_bool_project_id_rejected(temp_db):
    """``bool`` must not be coerced to ``1``."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, True, None, ""
        )
    with pytest.raises(ValueError):
        timeline_api.save_timeline_session_override(
            "2026-06-25", activity_ids, member_hash, False, None, ""
        )


def test_save_override_project_id_none_allowed(temp_db):
    """``project_id=None`` is valid (means no project override)."""
    ids = _seed_session()
    activity_ids, member_hash = _session_identity(ids[0])
    timeline_api.save_timeline_session_override(
        "2026-06-25", activity_ids, member_hash, None, None, ""
    )
    assert _session_note_count(ids[0]) == 0


# ---------------------------------------------------------------------------
# Legacy API disabled tests
# ---------------------------------------------------------------------------


def test_reclassify_timeline_session_project_deleted(temp_db):
    """The 2-param reclassify function has been deleted."""
    project = project_service.create_project("P")
    ids = _seed_session()
    assert not hasattr(timeline_api, "reclassify_timeline_session_project")
    with pytest.raises(AttributeError):
        timeline_api.reclassify_timeline_session_project(ids, project)


def test_update_timeline_session_note_first_activity_disabled(temp_db):
    """The first-activity form (3-param) of update_timeline_session_note is
    disabled; calling it must fail without writing an override row."""
    ids = _seed_session()
    with pytest.raises((ValueError, TypeError)):
        timeline_api.update_timeline_session_note("2026-06-25", ids[0], "note")
    assert _session_note_count(ids[0]) == 0


def test_update_timeline_session_note_and_duration_first_activity_disabled(temp_db):
    """The first-activity form (4-param) of
    update_timeline_session_note_and_duration is disabled; calling it must
    fail without writing an override row."""
    ids = _seed_session()
    with pytest.raises(ValueError):
        timeline_api.update_timeline_session_note_and_duration(
            "2026-06-25", ids[0], "note", 3600
        )
    assert _session_note_count(ids[0]) == 0
