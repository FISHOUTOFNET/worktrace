from __future__ import annotations

import pytest

from worktrace.services import activity_service, project_service, timeline_service
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot

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
