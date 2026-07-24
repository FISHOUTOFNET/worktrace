from __future__ import annotations

import pytest

from tests.support.activity_factory import create_closed_activity
from tests.support.db_helpers import assign_activity_project

from worktrace.services import project_service, view_model_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]

DATE = "2026-06-18"


def _assigned_activity(project_id: int, start: str, end: str, title: str) -> int:
    activity_id = create_closed_activity(
        day=DATE,
        start=start,
        end=end,
        app_name="Word",
        process_name="word.exe",
        window_title=title,
    )
    assign_activity_project(activity_id, project_id, manual=True)
    return activity_id


def test_deleted_project_does_not_increase_overview_project_count(temp_db):
    retained_project = project_service.create_project("Retained Project")
    deleted_project = project_service.create_project("Deleted Project")
    _assigned_activity(retained_project, "09:00:00", "09:30:00", "Retained.docx")
    _assigned_activity(deleted_project, "10:00:00", "10:30:00", "Deleted.docx")

    before = view_model_service.get_overview_view_model(DATE)
    assert before["overview"]["project_count"] == 2

    project_service.soft_delete_project(deleted_project)

    after = view_model_service.get_overview_view_model(DATE)
    assert after["overview"]["project_count"] == 1
    visible = [
        *(after.get("attention") or []),
        *(after.get("recent") or []),
        *([after["current_session"]] if after.get("current_session") else []),
    ]
    assert "Deleted Project" not in repr(visible)
