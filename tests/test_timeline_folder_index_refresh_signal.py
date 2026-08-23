from __future__ import annotations

from pathlib import Path

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


def test_manual_timeline_project_change_has_no_folder_index_side_effect(
    temp_db,
    monkeypatch,
):
    source_project = project_service.create_project("Source")
    target_project = project_service.create_project("Target")
    source = _session(source_project)

    monkeypatch.setattr(
        folder_index_maintenance_service,
        "note_unresolved_file_miss",
        lambda *_args, **_kwargs: pytest.fail(
            "Timeline project edits must not signal folder-index maintenance"
        ),
    )
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "request_refresh_for_unresolved_file_misses",
        lambda: pytest.fail(
            "Timeline project edits must not run folder-index maintenance"
        ),
    )

    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "manual-project-no-index-refresh",
        target_project,
        False,
        None,
        "",
    )

    assert result["ok"] is True
    assert result["outcome_type"] == "operation_committed"


def test_timeline_api_has_no_folder_index_dependency() -> None:
    text = Path(timeline_api.__file__).read_text(encoding="utf-8")
    assert "folder_index_maintenance_service" not in text
    assert "_manual_project_refresh_target" not in text
