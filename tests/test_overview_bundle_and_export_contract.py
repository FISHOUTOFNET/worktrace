from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.services import project_service
from worktrace.services.view_model_service import get_overview_view_model, get_timeline_view_model

pytestmark = [pytest.mark.db, pytest.mark.integration]


def test_overview_and_timeline_share_canonical_closed_projection(temp_db, monkeypatch):
    day = "2026-07-06"
    project = project_service.create_project("P")
    aid = activity_service.create_activity("App", "app.exe", "A", project_id=project, start_time=f"{day} 09:00:00")
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} 09:10:00")
    monkeypatch.setattr("worktrace.services.timeline_service.get_default_report_date", lambda today=None: day)
    overview = get_overview_view_model(today=day)
    timeline = get_timeline_view_model(day)
    assert overview["today_total_seconds"] == timeline["total_seconds"]
