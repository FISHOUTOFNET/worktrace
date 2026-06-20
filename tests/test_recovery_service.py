from worktrace.constants import STATUS_ERROR
from worktrace.services import activity_service, project_service, recovery_service, session_boundary_service, settings_service


def test_recovery_closes_open_record_with_heartbeat(temp_db):
    settings_service.set_setting("last_collector_heartbeat", "2026-06-18 09:10:00")
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    recovery_service.recover_unclosed_records()
    row = activity_service.get_activity(aid)
    assert row["end_time"] == "2026-06-18 09:10:00"
    assert row["duration_seconds"] == 600


def test_recovery_without_heartbeat_marks_error(temp_db):
    settings_service.set_setting("last_collector_heartbeat", "")
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2099-06-18 09:00:00"
    )
    recovery_service.recover_unclosed_records()
    assert activity_service.get_activity(aid)["status"] == STATUS_ERROR


def test_restart_boundary_is_recorded_once_from_last_shutdown(temp_db):
    settings_service.set_setting("last_collector_heartbeat", "2000-01-01 09:09:00")
    settings_service.set_setting("last_shutdown_at", "2000-01-01 09:10:00")

    recovery_service.record_restart_boundary_if_needed()
    recovery_service.record_restart_boundary_if_needed()

    boundaries = session_boundary_service.list_boundaries("2000-01-01 09:00:00", "2000-01-01 09:20:00")
    assert [(row["occurred_at"], row["reason"]) for row in boundaries] == [("2000-01-01 09:10:00", "restart")]


def test_recovery_splits_unclosed_cross_midnight_record(temp_db):
    project_id = project_service.create_project("A")
    settings_service.set_setting("last_collector_heartbeat", "2026-06-19 00:10:00")
    aid = activity_service.create_activity(
        "Word",
        "word.exe",
        "Doc",
        project_id=project_id,
        start_time="2026-06-18 23:50:00",
    )

    recovery_service.recover_unclosed_records()
    first = activity_service.get_activity(aid)
    rows = activity_service.get_activities_by_date("2026-06-19")
    boundaries = session_boundary_service.list_boundaries("2026-06-19 00:00:00", "2026-06-19 00:10:00")

    assert first["end_time"] == "2026-06-19 00:00:00"
    assert first["duration_seconds"] == 10 * 60
    assert len(rows) == 1
    assert rows[0]["start_time"] == "2026-06-19 00:00:00"
    assert rows[0]["end_time"] == "2026-06-19 00:10:00"
    assert rows[0]["duration_seconds"] == 10 * 60
    assert rows[0]["project_id"] == project_id
    assert ("2026-06-19 00:00:00", "midnight") in [
        (row["occurred_at"], row["reason"]) for row in boundaries
    ]
