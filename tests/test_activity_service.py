import sqlite3

import pytest

from tests.support.db_helpers import assign_activity_project
from worktrace.services import activity_service, project_service

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


def test_low_level_create_rejects_second_open_record(temp_db):
    first = activity_service.create_activity(
        "A", "a.exe", "A", start_time="2026-06-18 09:00:00"
    )
    with pytest.raises(sqlite3.IntegrityError):
        activity_service.create_activity(
            "B", "b.exe", "B", start_time="2026-06-18 09:10:00"
        )
    assert activity_service.get_activity(first)["end_time"] is None


def test_activity_duration_writes_are_monotonic(temp_db):
    activity_id = activity_service.create_activity(
        "Word", "winword.exe", "Spec", start_time="2026-06-18 09:00:00"
    )
    activity_service.set_activity_duration(activity_id, 120)
    activity_service.set_activity_duration(activity_id, 60)

    assert activity_service.get_activity(activity_id)["duration_seconds"] == 120

    activity_service.close_activity(
        activity_id,
        "2026-06-18 09:01:00",
        duration_seconds=90,
    )

    assert activity_service.get_activity(activity_id)["duration_seconds"] == 120


def test_close_activity_can_use_larger_projected_duration(temp_db):
    activity_id = activity_service.create_activity(
        "Word", "winword.exe", "Spec", start_time="2026-06-18 09:00:00"
    )

    activity_service.close_activity(
        activity_id,
        "2026-06-18 09:01:00",
        duration_seconds=180,
    )

    assert activity_service.get_activity(activity_id)["duration_seconds"] == 180
