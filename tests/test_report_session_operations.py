from __future__ import annotations

import pytest

from worktrace.db import get_connection
from worktrace.services import (
    activity_service,
    project_activity_summary_service,
    project_service,
    report_session_operation_service,
    session_boundary_service,
    statistics_service,
    timeline_service,
)


pytestmark = pytest.mark.db


DATE = "2026-07-01"


def _sessions(temp_db):
    project = project_service.create_project("Operation project")
    for index, app in enumerate(("Word", "Excel", "PowerPoint")):
        start_minute = index * 20
        start = f"{DATE} 09:{start_minute:02d}:00"
        end = f"{DATE} 09:{start_minute + 10:02d}:00"
        activity_id = activity_service.create_activity(app, f"{app}.exe", f"{app}-{index}", project_id=project, start_time=start)
        activity_service.close_activity(activity_id, end)
        if index < 2:
            session_boundary_service.record_boundary(end, "stopped")
    return timeline_service.get_project_sessions_by_date(DATE)


def _raw_snapshot():
    with get_connection() as conn:
        activities = [tuple(row) for row in conn.execute(
            "SELECT id, start_time, end_time, duration_seconds, app_name, process_name, window_title, file_path_hint, status, source, is_deleted, is_hidden FROM activity_log ORDER BY id"
        ).fetchall()]
        assignments = [tuple(row) for row in conn.execute("SELECT * FROM activity_project_assignment ORDER BY activity_id").fetchall()]
        projects = [tuple(row) for row in conn.execute("SELECT * FROM project ORDER BY id").fetchall()]
        rules = [tuple(row) for row in conn.execute("SELECT * FROM project_rule ORDER BY id").fetchall()]
    return activities, assignments, projects, rules


def _hide(session: dict, request_id: str) -> None:
    report_session_operation_service.hide_session(
        DATE, session["projection_instance_key"], session["projection_revision"], request_id
    )


def _copy(session: dict, request_id: str) -> None:
    report_session_operation_service.copy_session(
        DATE, session["projection_instance_key"], session["projection_revision"], request_id
    )


def _hide_activity(session: dict, summary_id: str, request_id: str) -> None:
    report_session_operation_service.hide_session_activity(
        DATE, session["projection_instance_key"], summary_id, session["projection_revision"], request_id
    )


def _merge(source: dict, direction: str, request_id: str) -> None:
    sessions = timeline_service.get_project_sessions_by_date(DATE)
    current = next(item for item in sessions if item["projection_instance_key"] == source["projection_instance_key"])
    index = sessions.index(current)
    target = sessions[index - 1 if direction == "previous" else index + 1]
    report_session_operation_service.merge_session(
        DATE,
        current["projection_instance_key"],
        direction,
        request_id,
        expected_projection_revision=current["projection_revision"],
        target_projection_instance_key=target["projection_instance_key"],
        target_expected_projection_revision=target["projection_revision"],
    )


def _split(session: dict, request_id: str) -> None:
    report_session_operation_service.split_session(
        DATE, session["projection_instance_key"], session["projection_revision"], request_id
    )


def test_report_session_operations_do_not_mutate_raw_activity_facts(temp_db):
    sessions = _sessions(temp_db)
    before = _raw_snapshot()
    _hide(sessions[0], "req-hide")
    _copy(sessions[1], "req-copy")
    copied = next(item for item in timeline_service.get_project_sessions_by_date(DATE) if item["projection_kind"] == "copy")
    summary = project_activity_summary_service.get_projection_session_activity_summary(copied["projection_instance_key"], DATE)[0]
    _hide_activity(copied, summary["summary_id"], "req-hide-activity")
    visible = timeline_service.get_project_sessions_by_date(DATE)
    _merge(visible[0], "next", "req-merge")
    merged = next(item for item in timeline_service.get_project_sessions_by_date(DATE) if item["projection_kind"] == "merge")
    _split(merged, "req-split")
    assert _raw_snapshot() == before


def test_merge_next_and_split_restores_origin_sessions(temp_db):
    sessions = _sessions(temp_db)
    _merge(sessions[0], "next", "req-merge-1")
    merged = next(item for item in timeline_service.get_project_sessions_by_date(DATE) if item["projection_kind"] == "merge")
    assert merged["duration_seconds"] == 20 * 60
    _merge(merged, "next", "req-merge-2")
    merged = next(item for item in timeline_service.get_project_sessions_by_date(DATE) if item["projection_kind"] == "merge")
    assert merged["duration_seconds"] == 30 * 60
    _split(merged, "req-split")
    restored = timeline_service.get_project_sessions_by_date(DATE)
    assert len(restored) == 2
    assert {item["projection_kind"] for item in restored} == {"base", "merge"}


def test_copy_and_hide_activity_are_scoped_to_projection_instance(temp_db):
    original = _sessions(temp_db)[0]
    original_total = statistics_service.get_summary(DATE, DATE)["total_duration"]
    _copy(original, "req-copy")
    copied = next(item for item in timeline_service.get_project_sessions_by_date(DATE) if item["projection_kind"] == "copy")
    assert statistics_service.get_summary(DATE, DATE)["total_duration"] == original_total + 10 * 60
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 3
    summary = project_activity_summary_service.get_projection_session_activity_summary(copied["projection_instance_key"], DATE)[0]
    _hide_activity(copied, summary["summary_id"], "req-hide-activity")
    final = timeline_service.get_project_sessions_by_date(DATE)
    assert all(item["projection_kind"] != "copy" for item in final)
    assert any(item["projection_instance_key"] == original["projection_instance_key"] for item in final)
    assert statistics_service.get_summary(DATE, DATE)["total_duration"] == original_total


def test_hide_session_removes_projected_total(temp_db):
    sessions = _sessions(temp_db)
    total = statistics_service.get_summary(DATE, DATE)["total_duration"]
    _hide(sessions[0], "req-hide")
    assert len(timeline_service.get_project_sessions_by_date(DATE)) == 2
    assert statistics_service.get_summary(DATE, DATE)["total_duration"] == total - 10 * 60
