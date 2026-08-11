from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.api import timeline_api
from worktrace.services import folder_index_maintenance_service, project_service

DATE = "2026-07-02"

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _session(project_id: int):
    activity_id = activity_service.create_activity(
        "App",
        "app.exe",
        "A",
        project_id=project_id,
        start_time=f"{DATE} 09:00:00",
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.close_activity(activity_id, f"{DATE} 09:10:00")
    return timeline_api.get_project_sessions_by_date(DATE)[0]


def test_manual_timeline_project_change_requests_target_refresh(temp_db, monkeypatch):
    source_project = project_service.create_project("Source")
    target_project = project_service.create_project("Target")
    source = _session(source_project)
    requested: list[int] = []
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "request_refresh_for_project",
        lambda project_id: requested.append(int(project_id)) or 0,
    )

    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "manual-project-refresh",
        target_project,
        False,
        None,
        "",
    )

    assert result["ok"] is True
    assert result["outcome_type"] == "operation_committed"
    assert requested == [target_project]


def test_note_only_edit_does_not_request_project_refresh(temp_db, monkeypatch):
    source_project = project_service.create_project("Source")
    source = _session(source_project)
    requested: list[int] = []
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "request_refresh_for_project",
        lambda project_id: requested.append(int(project_id)) or 0,
    )

    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "note-only-no-refresh",
        None,
        False,
        None,
        "note",
    )

    assert result["ok"] is True
    assert requested == []


def test_refresh_failure_does_not_fail_committed_timeline_edit(temp_db, monkeypatch):
    source_project = project_service.create_project("Source")
    target_project = project_service.create_project("Target")
    source = _session(source_project)

    def fail_refresh(_project_id: int) -> int:
        raise RuntimeError("index worker unavailable")

    monkeypatch.setattr(
        folder_index_maintenance_service,
        "request_refresh_for_project",
        fail_refresh,
    )

    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "manual-refresh-best-effort",
        target_project,
        False,
        None,
        "",
    )

    assert result["ok"] is True
    assert result["outcome_type"] == "operation_committed"
