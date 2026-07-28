from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.services import project_service, report_projection_provider
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
    assert overview["project_distribution"]["total_seconds"] == timeline["total_seconds"]
    assert overview["project_distribution"]["segments"] == [
        {
            "key": f"project:{project}",
            "project_id": project,
            "label": "P",
            "duration_seconds": 10 * 60,
            "is_uncategorized": False,
            "is_other": False,
        }
    ]


def test_overview_calls_get_day_projection_once(temp_db, monkeypatch):
    day = "2026-07-07"
    project = project_service.create_project("Single projection")
    aid = activity_service.create_activity(
        "App",
        "app.exe",
        "A",
        project_id=project,
        start_time=f"{day} 09:00:00",
    )
    activity_service.close_activity(aid, f"{day} 09:10:00")
    calls: list[str] = []
    original = report_projection_provider.get_day_projection

    def tracking_get_day_projection(report_date: str):
        calls.append(report_date)
        return original(report_date)

    monkeypatch.setattr(
        report_projection_provider,
        "get_day_projection",
        tracking_get_day_projection,
    )

    overview = get_overview_view_model(today=day)

    assert overview["ok"] is True
    assert calls == [day]
