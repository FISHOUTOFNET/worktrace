from __future__ import annotations

import pytest

from worktrace.constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from worktrace.db import get_connection
from worktrace.services import activity_service, session_note_service
from worktrace.services.activity_edit_policy import require_project_editable_activity

pytestmark = [pytest.mark.db, pytest.mark.contract]


DAY = "2026-06-25"


def _activity(
    *,
    status: str = STATUS_NORMAL,
    closed: bool = True,
) -> int:
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        status=status,
        start_time=f"{DAY} 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    if closed:
        activity_service.close_activity(aid, f"{DAY} 09:30:00")
    return aid


def _session_note_row(activity_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT note, adjusted_duration_seconds
            FROM project_session_note
            WHERE report_date = ? AND first_activity_id = ?
            """,
            (DAY, activity_id),
        ).fetchone()
    return dict(row) if row else None


def _mark_open(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET end_time = NULL WHERE id = ?",
            (activity_id,),
        )


def _mark_hidden(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE activity_log SET is_hidden = 1 WHERE id = ?", (activity_id,))


def _mark_deleted(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE activity_log SET is_deleted = 1 WHERE id = ?", (activity_id,))


def test_require_project_editable_activity_allows_normal_closed(temp_db):
    aid = _activity()

    row = require_project_editable_activity(aid)

    assert row["id"] == aid


def test_require_project_editable_activity_rejects_open_normal(temp_db):
    aid = _activity(closed=False)

    with pytest.raises(ValueError) as exc:
        require_project_editable_activity(aid)

    assert str(exc.value) == "activity_in_progress"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (STATUS_IDLE, "activity_not_project_activity"),
        (STATUS_PAUSED, "activity_not_project_activity"),
        (STATUS_ERROR, "activity_not_project_activity"),
        (STATUS_EXCLUDED, "activity_not_project_activity"),
    ],
)
def test_require_project_editable_activity_rejects_system_statuses(temp_db, status, code):
    aid = _activity(status=status)

    with pytest.raises(ValueError) as exc:
        require_project_editable_activity(aid)

    assert str(exc.value) == code


def test_require_project_editable_activity_rejects_hidden(temp_db):
    aid = _activity()
    _mark_hidden(aid)

    with pytest.raises(ValueError) as exc:
        require_project_editable_activity(aid)

    assert str(exc.value) == "activity_hidden"


def test_require_project_editable_activity_rejects_deleted(temp_db):
    aid = _activity()
    _mark_deleted(aid)

    with pytest.raises(ValueError) as exc:
        require_project_editable_activity(aid)

    assert str(exc.value) == "activity_deleted"


@pytest.mark.parametrize("bad_id", [999999, True, False, "1", 1.2, None, 0, -1])
def test_require_project_editable_activity_rejects_invalid_ids(temp_db, bad_id):
    with pytest.raises(ValueError) as exc:
        require_project_editable_activity(bad_id)

    assert str(exc.value) == "activity_not_found"


def test_set_session_note_allows_normal_closed(temp_db):
    aid = _activity()

    session_note_service.set_session_note(DAY, aid, "hello")

    assert _session_note_row(aid)["note"] == "hello"


def test_set_session_user_fields_allows_normal_closed_duration_override(temp_db):
    aid = _activity()

    session_note_service.set_session_user_fields(DAY, aid, "hello", 60)

    row = _session_note_row(aid)
    assert row["note"] == "hello"
    assert int(row["adjusted_duration_seconds"]) == 60


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (_mark_open, "activity_in_progress"),
        (_mark_hidden, "activity_hidden"),
        (_mark_deleted, "activity_deleted"),
    ],
)
def test_set_session_note_rejects_non_editable_and_leaves_no_dirty_row(temp_db, mutate, code):
    aid = _activity()
    mutate(aid)

    with pytest.raises(ValueError) as exc:
        session_note_service.set_session_note(DAY, aid, "blocked")

    assert str(exc.value) == code
    assert _session_note_row(aid) is None


@pytest.mark.parametrize("status", [STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR, STATUS_EXCLUDED])
def test_set_session_user_fields_rejects_system_rows_without_dirty_data(temp_db, status):
    aid = _activity(status=status)

    with pytest.raises(ValueError) as exc:
        session_note_service.set_session_user_fields(DAY, aid, "blocked", 30)

    assert str(exc.value) == "activity_not_project_activity"
    assert _session_note_row(aid) is None


def test_set_session_user_fields_clear_still_requires_editability(temp_db):
    aid = _activity()
    session_note_service.set_session_user_fields(DAY, aid, "keep", 30)
    session_note_service.set_session_user_fields(DAY, aid, "", None)
    assert _session_note_row(aid) is None

    hidden = _activity()
    _mark_hidden(hidden)
    with pytest.raises(ValueError) as exc:
        session_note_service.set_session_user_fields(DAY, hidden, "", None)

    assert str(exc.value) == "activity_hidden"
    assert _session_note_row(hidden) is None
