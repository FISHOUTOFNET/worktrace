from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.services import project_service, session_boundary_service, timeline_service
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.statistics_projection import build_statistics_summary_projection

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _closed(day: str, start: str, end: str, *, project_id=None, status="normal"):
    aid = activity_service.create_activity(
        "App", "app.exe", "A", project_id=project_id, status=status,
        start_time=f"{day} {start}",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} {end}")
    return aid


def test_same_project_rows_form_one_canonical_session(temp_db):
    day = "2026-07-03"
    project = project_service.create_project("P")
    _closed(day, "09:00:00", "09:10:00", project_id=project)
    _closed(day, "09:10:00", "09:20:00", project_id=project)
    sessions = timeline_service.get_project_sessions_by_date(day)
    assert len(sessions) == 1
    assert sessions[0]["duration_seconds"] == 1200
    assert sessions[0]["projection_instance_key"].startswith("base:")


def test_short_project_return_merges_to_one_wall_clock_session(temp_db):
    day = "2026-07-04"
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _closed(day, "09:00:00", "09:10:00", project_id=project_a)
    _closed(day, "09:10:00", "09:14:00", project_id=project_b)
    _closed(day, "09:14:00", "09:24:00", project_id=project_a)

    snapshot = build_visible_snapshot(day, day)
    assert len(snapshot.final_sessions) == 1
    session = snapshot.final_sessions[0]
    assert int(session["project_id"]) == project_a
    assert session["start_time"] == f"{day} 09:00:00"
    assert session["end_time"] == f"{day} 09:24:00"
    assert int(session["duration_seconds"]) == 24 * 60
    assert len(session["activity_ids"]) == 3

    statistics = build_statistics_summary_projection(snapshot)
    by_project = {
        str(item["display_name"]): int(item["duration_seconds"])
        for item in statistics.by_project
    }
    assert statistics.total_duration_seconds == 24 * 60
    assert by_project == {"A": 24 * 60}


def test_short_project_return_over_five_minutes_stays_split(temp_db):
    day = "2026-07-05"
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _closed(day, "09:00:00", "09:10:00", project_id=project_a)
    _closed(day, "09:10:00", "09:16:00", project_id=project_b)
    _closed(day, "09:16:00", "09:26:00", project_id=project_a)

    sessions = timeline_service.get_project_sessions_by_date(day)
    assert [item["project_name"] for item in sessions] == ["A", "B", "A"]
    assert [item["duration_seconds"] for item in sessions] == [600, 360, 600]


def test_short_project_return_merges_repeated_returns_greedily(temp_db):
    day = "2026-07-06"
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    project_c = project_service.create_project("C")
    _closed(day, "09:00:00", "09:10:00", project_id=project_a)
    _closed(day, "09:10:00", "09:14:00", project_id=project_b)
    _closed(day, "09:14:00", "09:24:00", project_id=project_a)
    _closed(day, "09:24:00", "09:28:00", project_id=project_c)
    _closed(day, "09:28:00", "09:38:00", project_id=project_a)

    sessions = timeline_service.get_project_sessions_by_date(day)
    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "A"
    assert sessions[0]["duration_seconds"] == 38 * 60
    assert len(sessions[0]["activity_ids"]) == 5


def test_short_project_return_keeps_local_greedy_choice(temp_db):
    day = "2026-07-07"
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _closed(day, "09:00:00", "09:10:00", project_id=project_a)
    _closed(day, "09:10:00", "09:11:00", project_id=project_b)
    _closed(day, "09:11:00", "09:12:00", project_id=project_a)
    _closed(day, "09:12:00", "09:22:00", project_id=project_b)

    sessions = timeline_service.get_project_sessions_by_date(day)
    assert [item["project_name"] for item in sessions] == ["A", "B"]
    assert [item["duration_seconds"] for item in sessions] == [12 * 60, 10 * 60]


def test_user_pause_boundary_blocks_short_project_return(temp_db):
    day = "2026-07-08"
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _closed(day, "09:00:00", "09:10:00", project_id=project_a)
    _closed(day, "09:10:00", "09:11:00", project_id=project_b)
    _closed(day, "09:11:00", "09:21:00", project_id=project_a)
    session_boundary_service.record_boundary(
        f"{day} 09:10:30",
        "user_pause",
    )

    sessions = timeline_service.get_project_sessions_by_date(day)
    assert [item["project_name"] for item in sessions] == ["A", "B", "A"]


def test_sleep_resume_boundary_allows_short_project_return(temp_db):
    day = "2026-07-09"
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _closed(day, "09:00:00", "09:10:00", project_id=project_a)
    _closed(day, "09:10:00", "09:11:00", project_id=project_b)
    _closed(day, "09:11:00", "09:21:00", project_id=project_a)
    session_boundary_service.record_boundary(
        f"{day} 09:10:30",
        "sleep_resume",
    )

    sessions = timeline_service.get_project_sessions_by_date(day)
    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "A"
    assert sessions[0]["duration_seconds"] == 21 * 60


def test_short_project_return_wall_clock_includes_small_unrecorded_gap(temp_db):
    day = "2026-07-10"
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _closed(day, "09:00:00", "09:10:00", project_id=project_a)
    _closed(day, "09:12:00", "09:13:00", project_id=project_b)
    _closed(day, "09:13:00", "09:23:00", project_id=project_a)

    snapshot = build_visible_snapshot(day, day)
    assert len(snapshot.final_sessions) == 1
    session = snapshot.final_sessions[0]
    assert session["project_name"] == "A"
    assert int(session["duration_seconds"]) == 23 * 60
    assert sum(
        int(row["duration_seconds"])
        for row in snapshot.final_contributions
        if row["projection_instance_key"] == session["projection_instance_key"]
    ) == 23 * 60
    assert sum(
        int(row["observed_duration_seconds"])
        for row in snapshot.final_contributions
        if row["projection_instance_key"] == session["projection_instance_key"]
    ) == 21 * 60


def test_paused_is_hard_boundary_and_suppressed(temp_db):
    day = "2026-07-03"
    project = project_service.create_project("P")
    _closed(day, "09:00:00", "09:10:00", project_id=project)
    _closed(day, "09:10:00", "09:11:00", status="paused")
    _closed(day, "09:11:00", "09:20:00", project_id=project)
    snapshot = build_visible_snapshot(day, day)
    assert len(snapshot.final_sessions) == 2
    assert sum(item["duration_seconds"] for item in snapshot.final_entries) == 1140


def test_unattributed_excluded_is_a_standalone_entry(temp_db):
    day = "2026-07-03"
    _closed(day, "09:00:00", "09:10:00", status="excluded")
    snapshot = build_visible_snapshot(day, day)
    assert len(snapshot.final_sessions) == 0
    assert len(snapshot.standalone_status_entries) == 1
    assert snapshot.final_entries == snapshot.standalone_status_entries


def test_activity_id_details_and_preview_paths_are_deleted():
    assert not hasattr(timeline_service, "get_session_activity_details")
    assert not hasattr(timeline_service, "get_session_anchor_folders")
    assert not hasattr(timeline_service, "preview_session_project_update")
