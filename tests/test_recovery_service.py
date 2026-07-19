from tests.support import runtime_state_fixture
import pytest

pytestmark = [pytest.mark.collector_runtime, pytest.mark.integration, pytest.mark.db]

from tests.support import activity_factory as activity_service
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import STATUS_ERROR
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    activity_lifecycle_service,
    project_service,
    recovery_service,
    session_boundary_service,
    settings_service,
    startup_recovery_job_repository,
)


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

    boundaries = session_boundary_service.list_boundaries(
        "2000-01-01 09:00:00", "2000-01-01 09:20:00"
    )
    assert [(row["occurred_at"], row["reason"]) for row in boundaries] == [
        ("2000-01-01 09:10:00", "restart")
    ]


def test_recovery_splits_small_cross_midnight_record_synchronously(temp_db):
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
    boundaries = session_boundary_service.list_boundaries(
        "2026-06-19 00:00:00", "2026-06-19 00:10:00"
    )

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


def test_long_cross_midnight_recovery_uses_durable_bounded_continuation(temp_db):
    project_id = project_service.create_project("Long recovery")
    settings_service.set_setting("last_collector_heartbeat", "2026-06-10 00:10:00")
    aid = activity_service.create_activity(
        "Word",
        "word.exe",
        "Long.docx",
        project_id=project_id,
        start_time="2026-06-01 23:50:00",
    )

    recovery_service.recover_unclosed_records()

    original = activity_service.get_activity(aid)
    assert original["end_time"] == "2026-06-02 00:00:00"
    assert original["duration_seconds"] == 10 * 60
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM startup_recovery_job ORDER BY id"
        ).fetchall()
        created_segments = conn.execute(
            "SELECT COUNT(*) AS value FROM activity_log WHERE id <> ?",
            (aid,),
        ).fetchone()["value"]
    assert len(rows) == 1
    assert created_segments == 0
    assert rows[0]["cursor_time"] == "2026-06-02 00:00:00"
    assert rows[0]["end_time"] == "2026-06-10 00:10:00"

    batch_sizes: list[int] = []
    for _ in range(10):
        with get_connection() as conn:
            jobs = startup_recovery_job_repository.list_runnable_jobs(conn, limit=1)
        if not jobs:
            break
        job = jobs[0]
        commands, boundaries, next_cursor, completed = (
            recovery_service._plan_continuation_batch(job, 2)
        )
        batch_sizes.append(len(commands))
        activity_lifecycle_service.recover_continuation_batch(
            job_id=int(job["id"]),
            commands=commands,
            boundaries=boundaries,
            next_cursor=next_cursor,
            completed=completed,
        )
    else:
        pytest.fail("startup recovery continuation did not complete")

    assert batch_sizes
    assert max(batch_sizes) <= 2
    with get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS value FROM startup_recovery_job"
        ).fetchone()["value"] == 0
        segments = conn.execute(
            """
            SELECT start_time, end_time, duration_seconds
            FROM activity_log
            WHERE id <> ?
            ORDER BY start_time
            """,
            (aid,),
        ).fetchall()
    assert len(segments) == 9
    assert segments[0]["start_time"] == "2026-06-02 00:00:00"
    assert segments[-1]["end_time"] == "2026-06-10 00:10:00"
    assert sum(int(row["duration_seconds"]) for row in segments) == (
        8 * 24 * 60 * 60 + 10 * 60
    )


def test_recovery_clears_stale_runtime_state_without_open_row(temp_db):
    settings_service.set_setting("last_collector_heartbeat", "2000-01-01 09:09:00")
    settings_service.set_setting("last_shutdown_at", "2000-01-01 09:10:00")
    runtime_state_fixture.set_setting("pending_short_seconds", "12")
    runtime_state_fixture.set_setting("current_activity_snapshot", '{"status":"normal"}')

    recovery_service.recover_unclosed_records()

    assert runtime_state_fixture.get_setting("pending_short_seconds") == "0"
    assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == ""

    machine = CollectorStateMachine()
    window = ActiveWindow("A", "a.exe", "A")
    machine.transition_to("recording", window, at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", window, at_time="2026-06-18 09:00:30")
    machine.transition_to("stopped", at_time="2026-06-18 09:00:30")

    rows = activity_service.get_activities_by_date("2026-06-18")
    assert len(rows) == 1
    assert rows[0]["duration_seconds"] == 30
