from worktrace.services import activity_service, project_service


def test_create_close_and_manual_updates(temp_db):
    pid = project_service.create_project("Client")
    activity_id = activity_service.create_activity(
        "Word", "winword.exe", "Spec", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(activity_id, "2026-06-18 09:30:00")
    activity_service.update_activity_project(activity_id, pid)
    activity_service.update_activity_note(activity_id, "done")
    row = activity_service.get_activity(activity_id)
    assert row["duration_seconds"] == 1800
    assert row["project_id"] == pid
    assert row["manual_override"] == 1
    assert row["note"] == "done"


def test_create_activity_closes_existing_open_record(temp_db):
    first = activity_service.create_activity(
        "A", "a.exe", "A", start_time="2026-06-18 09:00:00"
    )
    second = activity_service.create_activity(
        "B", "b.exe", "B", start_time="2026-06-18 09:10:00"
    )
    assert activity_service.get_activity(first)["end_time"] == "2026-06-18 09:10:00"
    assert activity_service.get_open_activity()["id"] == second


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
