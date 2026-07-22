"""Authoritative DTO additions required by the redesigned pages."""
from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.services import project_service, statistics_service
from worktrace.services.view_model_service import get_overview_view_model

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.webview_static]


def _closed(project_id: int, start: str, end: str, title: str) -> int:
    activity_id = activity_service.create_activity(
        "Editor", "editor.exe", title, project_id=project_id, start_time=start
    )
    activity_service.close_activity(activity_id, end)
    return activity_id


def test_overview_groups_are_disjoint_and_derived_summary_is_not_user_description(temp_db):
    project_id = project_service.create_project("Client")
    _closed(project_id, "2026-07-22 09:00:00", "2026-07-22 09:30:00", "brief.docx")

    model = get_overview_view_model("2026-07-22")
    attention = model["attention"]
    recent = model["recent"]
    assert len(attention) <= 3
    assert attention and attention[0]["needs_user_description"] is True
    assert attention[0]["description_source"] in {"derived", "none"}
    assert attention[0]["user_description"] == ""
    keys = lambda rows: {row["projection_instance_key"] for row in rows}
    assert keys(attention).isdisjoint(keys(recent))
    if model["current_session"]:
        assert model["current_session"]["projection_instance_key"] not in keys(attention + recent)


def test_statistics_all_time_and_project_scope_use_one_authoritative_projection(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _closed(project_a, "2026-07-20 09:00:00", "2026-07-20 09:20:00", "a.txt")
    _closed(project_b, "2026-07-21 10:00:00", "2026-07-21 10:10:00", "b.txt")

    all_time = statistics_service.get_statistics_export_summary("", "")
    only_a = statistics_service.get_statistics_export_summary("", "", str(project_a))
    assert all_time["total_duration_seconds"] == 30 * 60
    assert only_a["total_duration_seconds"] == 20 * 60
    assert only_a["project_count"] == 1
    assert {row["display_name"] for row in only_a["by_project"]} == {"A"}
    assert only_a["project_id"] == str(project_a)


def test_project_rules_summary_is_backend_owned(temp_db):
    project_id = project_service.create_project("Summary Project", "Shown in search")
    _closed(project_id, "2026-07-22 11:00:00", "2026-07-22 11:15:00", "summary.txt")
    project = next(row for row in project_service.list_project_bindings() if row["id"] == project_id)
    assert project["description"] == "Shown in search"
    assert project["last_used_at"]
    assert project["total_duration_seconds"] == 15 * 60
