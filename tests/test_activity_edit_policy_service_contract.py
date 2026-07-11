from __future__ import annotations

import json

import pytest

from worktrace.constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from worktrace.db import get_connection
from worktrace.services import activity_service, report_session_operation_service, timeline_service
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
            SELECT o.payload_json
            FROM report_session_operation o
            JOIN report_session_operation_member m ON m.operation_id = o.id
            WHERE o.report_date = ?
              AND m.activity_id = ?
              AND o.operation_type = 'edit_session'
              AND o.match_state = 'active'
            ORDER BY o.replay_order DESC, o.id DESC
            LIMIT 1
            """,
            (DAY, activity_id),
        ).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    return {
        "note": (payload.get("note") or {}).get("value", ""),
        "adjusted_duration_seconds": (payload.get("duration") or {}).get("value"),
    }


def _update_session_note_and_duration(
    day: str,
    activity_ids: list[int],
    member_hash: str,
    note: str,
    adjusted_duration_seconds: int | None,
) -> None:
    for activity_id in activity_ids:
        require_project_editable_activity(activity_id)
    session = next(
        (
            item
            for item in timeline_service.get_project_sessions_by_date(day)
            if [int(aid) for aid in item.get("activity_ids") or []] == [int(aid) for aid in activity_ids]
            and item.get("activity_member_hash") == member_hash
        ),
        None,
    )
    if not session:
        raise ValueError("session_identity_conflict")
    count = getattr(_update_session_note_and_duration, "_count", 0) + 1
    setattr(_update_session_note_and_duration, "_count", count)
    report_session_operation_service.edit_session(
        day,
        session["projection_instance_key"],
        session["projection_revision"],
        f"test-edit-policy-{count}",
        project_id=session.get("project_id"),
        adjusted_duration_seconds=adjusted_duration_seconds,
        note=note,
    )


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
    session = timeline_service.get_project_sessions_by_date(DAY)[0]

    _update_session_note_and_duration(
        DAY, session["activity_ids"], session["activity_member_hash"], "hello", None
    )

    assert _session_note_row(aid)["note"] == "hello"


def test_set_session_user_fields_allows_normal_closed_duration_override(temp_db):
    aid = _activity()
    session = timeline_service.get_project_sessions_by_date(DAY)[0]

    _update_session_note_and_duration(
        DAY, session["activity_ids"], session["activity_member_hash"], "hello", 60
    )

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
        _update_session_note_and_duration(
            DAY, [aid], "a" * 40, "blocked", None
        )

    assert str(exc.value) == code
    assert _session_note_row(aid) is None


@pytest.mark.parametrize("status", [STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR, STATUS_EXCLUDED])
def test_set_session_user_fields_rejects_system_rows_without_dirty_data(temp_db, status):
    aid = _activity(status=status)

    with pytest.raises(ValueError) as exc:
        _update_session_note_and_duration(
            DAY, [aid], "a" * 40, "blocked", 30
        )

    assert str(exc.value) == "activity_not_project_activity"
    assert _session_note_row(aid) is None


def test_set_session_user_fields_clear_still_requires_editability(temp_db):
    aid = _activity()
    session = timeline_service.get_project_sessions_by_date(DAY)[0]
    _update_session_note_and_duration(
        DAY, session["activity_ids"], session["activity_member_hash"], "keep", 30
    )
    _update_session_note_and_duration(
        DAY, session["activity_ids"], session["activity_member_hash"], "", None
    )
    cleared = _session_note_row(aid)
    assert cleared == {"note": "", "adjusted_duration_seconds": None}

    hidden = _activity()
    _mark_hidden(hidden)
    with pytest.raises(ValueError) as exc:
        _update_session_note_and_duration(
            DAY, [hidden], "a" * 40, "", None
        )

    assert str(exc.value) == "activity_hidden"
    assert _session_note_row(hidden) is None
