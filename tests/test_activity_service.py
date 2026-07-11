from tests.support.db_helpers import assign_activity_project
from worktrace.services import activity_service, project_service
import pytest

pytestmark = [pytest.mark.db]


def test_create_close_and_manual_updates(temp_db):
    pid = project_service.create_project("Client")
    activity_id = activity_service.create_activity(
        "Word", "winword.exe", "Spec", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(activity_id, "2026-06-18 09:30:00")
    assign_activity_project(activity_id, pid)
    row = activity_service.get_activity(activity_id)
    assert row["duration_seconds"] == 1800
    assert row["project_id"] == pid
    assert row["assignment_is_manual"] == 1


def test_create_activity_does_not_close_existing_open_record(temp_db):
    """``create_activity`` is a pure low-level insert: it does NOT close
    pre-existing open rows. Production open-row lifecycle must use
    ``activity_lifecycle_service.start_activity`` which closes pre-existing
    open rows + finalizes them + inserts the new row."""
    first = activity_service.create_activity(
        "A", "a.exe", "A", start_time="2026-06-18 09:00:00"
    )
    second = activity_service.create_activity(
        "B", "b.exe", "B", start_time="2026-06-18 09:10:00"
    )
    # Both rows remain open — create_activity is pure CRUD.
    assert activity_service.get_activity(first)["end_time"] is None
    assert activity_service.get_activity(second)["end_time"] is None


def test_activity_duration_writes_are_monotonic(temp_db):
    activity_id = activity_service.create_activity(
        "Word", "winword.exe", "Spec", start_time="2026-06-18 09:00:00"
    )
    activity_service.set_activity_duration(activity_id, 120)
    activity_service.set_activity_duration(activity_id, 60)

    assert activity_service.get_activity(activity_id)["duration_seconds"] == 120

    activity_service.close_activity(activity_id, "2026-06-18 09:01:00", duration_seconds=90)

    assert activity_service.get_activity(activity_id)["duration_seconds"] == 120


def test_close_activity_can_use_larger_projected_duration(temp_db):
    activity_id = activity_service.create_activity(
        "Word", "winword.exe", "Spec", start_time="2026-06-18 09:00:00"
    )

    activity_service.close_activity(activity_id, "2026-06-18 09:01:00", duration_seconds=180)

    assert activity_service.get_activity(activity_id)["duration_seconds"] == 180
