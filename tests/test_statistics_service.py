from tests.support import runtime_state_fixture
from tests.support import activity_factory as activity_service
from tests.support.db_helpers import assign_activity_project
import json
from datetime import date

from worktrace.services import project_service, session_boundary_service, settings_service, statistics_service
import pytest

pytestmark = [pytest.mark.db]


def test_statistics_aggregation(temp_db):
    pid = project_service.create_project("Client")
    a = activity_service.create_activity(
        "Word", "word.exe", "Client", project_id=pid, start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(a, "2026-06-18 10:00:00")
    idle = activity_service.create_activity("空闲", "idle", "用户空闲", status="idle", start_time="2026-06-18 10:00:00")
    activity_service.close_activity(idle, "2026-06-18 10:15:00")
    summary = statistics_service.get_summary("2026-06-18", "2026-06-18")
    assert summary["total_duration"] == 4500
    assert summary["effective_duration"] == 3600
    assert summary["classified_duration"] == 4500
    assert summary["idle_duration"] == 900
    stats = statistics_service.get_project_stats("2026-06-18", "2026-06-18")
    assert stats[0]["project"] == "Client"
    assert stats[0]["total_duration"] == 4500


def test_summary_read_does_not_materialize_context(temp_db):
    summary = statistics_service.get_summary("2026-06-18", "2026-06-19")
    assert summary["total_duration"] == 0


def test_project_stats_count_context_assigned_short_gap(temp_db):
    project_a = project_service.create_project("A")
    a1 = activity_service.create_activity(
        "Word", "word.exe", "A1.docx", project_id=project_a, start_time="2026-06-18 09:00:00"
    )
    activity_service.finalize_created_activity(a1)
    activity_service.close_all_open_rows("2026-06-18 09:05:00")
    b = activity_service.create_activity(
        "Word", "word.exe", "Unassigned.docx", start_time="2026-06-18 09:05:00"
    )
    activity_service.finalize_created_activity(b)
    activity_service.close_all_open_rows("2026-06-18 09:09:00")
    a2 = activity_service.create_activity(
        "Word", "word.exe", "A2.docx", project_id=project_a, start_time="2026-06-18 09:09:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_all_open_rows("2026-06-18 09:15:00")

    stats = statistics_service.get_project_stats("2026-06-18", "2026-06-18")
    assert stats == [{"project": "A", "total_duration": 900, "record_count": 1}]
    assert activity_service.get_activity(b)["project_id"] != project_a


def test_statistics_split_cross_midnight_projects_by_calendar_day(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    a1 = activity_service.create_activity(
        "Word", "word.exe", "A1.docx", project_id=project_a, start_time="2026-06-18 23:50:00"
    )
    activity_service.finalize_created_activity(a1)
    activity_service.close_all_open_rows("2026-06-19 00:10:00")
    a2 = activity_service.create_activity(
        "Word", "word.exe", "A2.docx", project_id=project_a, start_time="2026-06-19 00:10:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_all_open_rows("2026-06-19 00:30:00")
    b = activity_service.create_activity(
        "Word", "word.exe", "B1.docx", project_id=project_b, start_time="2026-06-19 00:30:00"
    )
    activity_service.finalize_created_activity(b)
    activity_service.close_all_open_rows("2026-06-19 00:45:00")
    idle = activity_service.create_activity(
        "空闲", "idle", "用户空闲", status="idle", start_time="2026-06-19 00:45:00"
    )
    activity_service.finalize_created_activity(idle)
    activity_service.close_all_open_rows("2026-06-19 01:15:00")

    previous = statistics_service.get_summary("2026-06-18", "2026-06-18")
    current = statistics_service.get_summary("2026-06-19", "2026-06-19")

    assert previous["total_duration"] == 10 * 60
    assert previous["classified_duration"] == 10 * 60
    assert statistics_service.get_project_stats("2026-06-18", "2026-06-18") == [
        {"project": "A", "total_duration": 10 * 60, "record_count": 1}
    ]
    assert current["total_duration"] == 45 * 60
    assert current["effective_duration"] == 45 * 60
    assert current["idle_duration"] == 0
    assert statistics_service.get_project_stats("2026-06-19", "2026-06-19") == [
        {"project": "A", "total_duration": 30 * 60, "record_count": 1},
        {"project": "B", "total_duration": 15 * 60, "record_count": 1},
    ]


def test_project_stats_count_project_records_split_by_boundary(temp_db):
    project_a = project_service.create_project("A")
    first = activity_service.create_activity(
        "Word", "word.exe", "A1.docx", project_id=project_a, start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(first, "2026-06-18 09:10:00")
    session_boundary_service.record_boundary("2026-06-18 09:10:00", "stopped")
    second = activity_service.create_activity(
        "Word", "word.exe", "A2.docx", project_id=project_a, start_time="2026-06-18 09:20:00"
    )
    activity_service.close_activity(second, "2026-06-18 09:30:00")

    assert statistics_service.get_project_stats("2026-06-18", "2026-06-18") == [
        {"project": "A", "total_duration": 20 * 60, "record_count": 2}
    ]


def _persisted_open_snapshot(
    *,
    aid: int,
    start_time: str,
    display_name: str = "ProjectA",
) -> dict:
    return {
        "app_name": "AppA",
        "process_name": "AppA.exe",
        "start_time": start_time,
        "elapsed_seconds": 60,
        "status": "normal",
        "is_persisted": True,
        "persisted_activity_id": aid,
        "display_project": {
            "id": 12,
            "name": display_name,
            "description": display_name + " description",
            "source": "keyword_rule",
            "is_uncategorized": False,
            "is_suggested_project": False,
        },
    }


def test_statistics_export_excludes_in_progress_live_rows(temp_db):
    """Statistics / Export pages remain closed-only."""
    from datetime import datetime, timedelta
    from worktrace.constants import TIME_FORMAT

    today = date.today().isoformat()
    project_b_id = project_service.create_project("ProjectB")
    start = datetime.now() - timedelta(seconds=60)
    start_time = start.strftime(TIME_FORMAT)
    aid = activity_service.create_activity(
        "AppA", "AppA.exe", "Window", start_time=start_time
    )
    assign_activity_project(aid, project_b_id)
    activity_service.set_activity_duration(aid, 60)

    snapshot = _persisted_open_snapshot(aid=aid, start_time=start_time)
    runtime_state_fixture.set_setting(
        "current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False)
    )
    settings_service.clear_settings_cache()

    export_summary = statistics_service.get_statistics_export_summary(today, today)
    assert export_summary["total_duration_seconds"] == 0
    assert export_summary["activity_count"] == 0
    assert export_summary["by_project"] == []
    assert export_summary["by_app"] == []
    assert export_summary["by_status"] == []


def test_legacy_confirmation_constants_are_disabled():
    from worktrace.constants import (
        HISTORY_PERSIST_THRESHOLD_SECONDS,
        PROJECT_OWNERSHIP_CONFIRM_SECONDS,
    )

    assert HISTORY_PERSIST_THRESHOLD_SECONDS == 0
    assert PROJECT_OWNERSHIP_CONFIRM_SECONDS == 0


def test_project_ownership_service_has_no_confirm_window():
    from inspect import signature

    from worktrace.services.project_ownership_service import (
        ProjectLabel,
        ProjectOwnershipState,
        begin_ownership_for_new_resource,
    )

    official = ProjectLabel(name="ProjectA", id=12, source="keyword_rule")
    state = begin_ownership_for_new_resource(official)
    assert state == ProjectOwnershipState(
        display_project=official,
        candidate_project=official,
    )
    assert tuple(signature(begin_ownership_for_new_resource).parameters) == ("candidate",)
    assert not hasattr(state, "project_transition")
    assert not hasattr(state, "last_confirmed_project")
