from worktrace.constants import STATUS_ERROR
from worktrace.services import activity_service, recovery_service, session_boundary_service, settings_service


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
