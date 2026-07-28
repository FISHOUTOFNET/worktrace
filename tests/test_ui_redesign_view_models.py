"""Authoritative DTO additions required by the redesigned pages."""
from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.api import project_api
from worktrace.api.application_capabilities import RulesApplicationService
from worktrace.services import (
    project_service,
    report_projection_snapshot_service,
    statistics_service,
)
from worktrace.services.view_model_service import get_overview_view_model

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.webview_static]


def _closed(project_id: int, start: str, end: str, title: str) -> int:
    activity_id = activity_service.create_activity(
        "Editor", "editor.exe", title, project_id=project_id, start_time=start
    )
    activity_service.close_activity(activity_id, end)
    return activity_id


def test_overview_recent_keeps_derived_summary_and_shared_attention_facts(temp_db):
    project_id = project_service.create_project("Client")
    _closed(project_id, "2026-07-22 09:00:00", "2026-07-22 09:30:00", "brief.docx")

    model = get_overview_view_model("2026-07-22")
    recent = model["recent"]
    assert recent and recent[0]["needs_user_description"] is True
    assert recent[0]["description_source"] in {"derived", "none"}
    assert recent[0]["user_description"] == ""
    assert recent[0]["needs_attention"] is True
    assert recent[0]["missing_fields"] == "description"
    assert "attention" not in model
    assert "attention_remaining_count" not in model


def test_overview_in_progress_session_appears_first_in_recent(temp_db):
    project_id = project_service.create_project("Live")
    activity_id = activity_service.create_activity(
        "Editor", "editor.exe", "live-doc.md", project_id=project_id,
        start_time="2026-07-22 10:00:00",
    )

    model = get_overview_view_model("2026-07-22")
    recent = model["recent"]
    assert recent
    assert recent[0]["is_in_progress"] is True
    assert model["current_session"] is not None
    assert model["current_session"]["projection_instance_key"] == recent[0]["projection_instance_key"]
    assert recent[0]["needs_attention"] is False
    activity_service.close_activity(activity_id, "2026-07-22 10:30:00")


def test_overview_recent_truncation_does_not_affect_kpi_totals(temp_db):
    """Verify that truncating the recent list to _RECENT_LIMIT does not
    affect KPI totals. Uses two alternating projects so each activity
    becomes an independent report session (same-project back-to-back
    activities would merge into one session, making the test ineffective)."""
    from worktrace.services import view_model_service

    recent_limit = view_model_service._RECENT_LIMIT
    project_a = project_service.create_project("KPI-A")
    project_b = project_service.create_project("KPI-B")
    num_sessions = recent_limit + 2

    for index in range(num_sessions):
        start_minute = index * 10
        start_hour = 8 + start_minute // 60
        start_min = start_minute % 60
        end_minute = start_minute + 10
        end_hour = 8 + end_minute // 60
        end_min = end_minute % 60
        project_id = project_a if index % 2 == 0 else project_b
        _closed(
            project_id,
            f"2026-07-22 {start_hour:02d}:{start_min:02d}:00",
            f"2026-07-22 {end_hour:02d}:{end_min:02d}:00",
            f"file{index}.txt",
        )

    model = get_overview_view_model("2026-07-22")
    assert len(model["recent"]) == recent_limit
    # KPI totals are computed from the full projection, not the truncated list.
    expected_total = num_sessions * 10 * 60
    assert model["today_total_seconds"] == expected_total
    assert model["classified_seconds"] == expected_total
    assert model["overview"]["today_total_seconds"] == model["today_total_seconds"]


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


def test_project_catalog_read_does_not_build_full_history_snapshot(temp_db, monkeypatch):
    project_id = project_service.create_project("Catalog Project")

    def forbidden_snapshot(*args, **kwargs):
        raise AssertionError("project catalog must not build the all-time report snapshot")

    monkeypatch.setattr(
        report_projection_snapshot_service,
        "build_visible_snapshot",
        forbidden_snapshot,
    )

    project = next(
        row for row in project_service.list_project_bindings() if row["id"] == project_id
    )
    assert "total_duration_seconds" not in project
    assert project["name"] == "Catalog Project"


def test_rules_application_service_routes_to_lightweight_catalog(monkeypatch):
    expected = [{"id": 1, "name": "Lightweight Project"}]

    monkeypatch.setattr(
        project_api,
        "list_project_bindings",
        lambda: expected,
    )

    assert not hasattr(project_api, "list_project_rule_summaries")
    assert RulesApplicationService().list_project_bindings() == expected
