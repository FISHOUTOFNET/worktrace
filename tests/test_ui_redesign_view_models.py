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


def test_overview_attention_is_subset_of_recent_and_derived_summary_is_not_user_description(temp_db):
    project_id = project_service.create_project("Client")
    _closed(project_id, "2026-07-22 09:00:00", "2026-07-22 09:30:00", "brief.docx")

    model = get_overview_view_model("2026-07-22")
    attention = model["attention"]
    recent = model["recent"]
    assert len(attention) <= 3
    assert attention and attention[0]["needs_user_description"] is True
    assert attention[0]["description_source"] in {"derived", "none"}
    assert attention[0]["user_description"] == ""
    # 待整理 is an action subset of 最近记录, not a disjoint partition: every
    # attention row must also appear in recent.
    recent_keys = {row["projection_instance_key"] for row in recent}
    attention_keys = {row["projection_instance_key"] for row in attention}
    assert attention_keys <= recent_keys


def test_overview_in_progress_session_appears_first_in_recent_and_not_in_attention(temp_db):
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
    # In-progress sessions never enter attention (attention requires ended).
    attention_keys = {row["projection_instance_key"] for row in model["attention"]}
    assert recent[0]["projection_instance_key"] not in attention_keys
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
    # Truncation must actually happen: exactly _RECENT_LIMIT rows, not fewer.
    # If sessions merged, this would be less than recent_limit.
    assert len(model["recent"]) == recent_limit
    # KPI totals are computed from the full projection, not the truncated list.
    expected_total = num_sessions * 10 * 60
    assert model["today_total_seconds"] == expected_total
    assert model["classified_seconds"] == expected_total
    assert model["overview"]["today_total_seconds"] == model["today_total_seconds"]


def _organize_session(row, index, report_date):
    """Set a user description on a session so it no longer needs attention."""
    from worktrace.services import report_session_operation_service

    report_session_operation_service.edit_session(
        report_date=report_date,
        projection_instance_key=row["projection_instance_key"],
        expected_projection_revision=row["projection_revision"],
        request_id=f"organize-{index}",
        project_id=None,
        adjusted_duration_seconds=None,
        note=f"organized-{index}",
    )


def test_overview_attention_subset_preserved_across_recent_truncation(temp_db):
    """When recent is truncated to _RECENT_LIMIT, an older attention record
    that falls beyond the truncation window must still appear in visible
    recent. This verifies the selection function promotes required attention
    rows into the visible recent window so visible attention ⊆ visible recent.
    """
    from worktrace.services import view_model_service

    recent_limit = view_model_service._RECENT_LIMIT
    attention_limit = view_model_service._ATTENTION_LIMIT
    report_date = "2026-07-22"
    project_a = project_service.create_project("Alpha")
    project_b = project_service.create_project("Beta")
    # Create recent_limit + 2 sessions, alternating projects to prevent
    # merging. Each session is 10 minutes, back-to-back.
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
            f"{report_date} {start_hour:02d}:{start_min:02d}:00",
            f"{report_date} {end_hour:02d}:{end_min:02d}:00",
            f"file{index}.txt",
        )

    # All sessions currently need attention (no user description). Set notes
    # on the newest recent_limit sessions so only the 2 oldest need attention.
    model = get_overview_view_model(report_date)
    # recent is sorted newest-first; organize the first recent_limit rows.
    for index, row in enumerate(model["recent"][:recent_limit]):
        _organize_session(row, index, report_date)

    # Re-fetch: the 2 oldest sessions (beyond recent_limit) now need
    # attention and must be promoted into visible recent.
    model = get_overview_view_model(report_date)
    attention_keys = {row["projection_instance_key"] for row in model["attention"]}
    recent_keys = {row["projection_instance_key"] for row in model["recent"]}

    assert attention_keys, "there must be attention rows"
    assert len(model["attention"]) <= attention_limit
    assert attention_keys <= recent_keys, (
        "visible attention must be a subset of visible recent"
    )
    assert len(model["recent"]) == recent_limit


def test_overview_attention_promotion_replaces_tail_ordinary_rows(temp_db):
    """Verify the replacement strategy: to accommodate older attention rows
    that fell beyond the truncation boundary, the selection function replaces
    tail-most ordinary (non-in-progress, non-attention) rows. The in-progress
    session (if present) stays first and is never replaced, and the remaining
    newer ordinary rows keep their relative order.
    """
    from worktrace.services import view_model_service

    recent_limit = view_model_service._RECENT_LIMIT
    report_date = "2026-07-22"
    project_a = project_service.create_project("Promo-A")
    project_b = project_service.create_project("Promo-B")
    # 1 in-progress session (newest) + recent_limit closed organized sessions
    # + 2 closed unorganized sessions (oldest, need attention).
    # Total = recent_limit + 3 sessions.
    num_organized_closed = recent_limit - 1  # reserve 1 slot for in-progress
    num_unorganized = 2
    total_closed = num_organized_closed + num_unorganized
    # Closed sessions first (oldest to newest), then the open one.
    for index in range(total_closed):
        start_minute = index * 10
        start_hour = 8 + start_minute // 60
        start_min = start_minute % 60
        end_minute = start_minute + 10
        end_hour = 8 + end_minute // 60
        end_min = end_minute % 60
        project_id = project_a if index % 2 == 0 else project_b
        _closed(
            project_id,
            f"{report_date} {start_hour:02d}:{start_min:02d}:00",
            f"{report_date} {end_hour:02d}:{end_min:02d}:00",
            f"file{index}.txt",
        )

    # Organize the newest num_organized_closed closed sessions (all except
    # the 2 oldest). The 2 oldest remain unorganized → need attention.
    model = get_overview_view_model(report_date)
    # recent is sorted: in-progress first (if any), then closed newest-first.
    # Organize all closed sessions except the last 2 (which are the oldest).
    closed_rows = [row for row in model["recent"] if not row.get("is_in_progress")]
    rows_to_organize = closed_rows[:num_organized_closed]
    for index, row in enumerate(rows_to_organize):
        _organize_session(row, index, report_date)

    # Create an in-progress session as the newest activity.
    live_activity_id = activity_service.create_activity(
        "Editor", "editor.exe", "live-doc.md", project_id=project_a,
        start_time=f"{report_date} 12:00:00",
    )

    model = get_overview_view_model(report_date)
    attention_keys = {row["projection_instance_key"] for row in model["attention"]}
    recent_keys = {row["projection_instance_key"] for row in model["recent"]}

    # In-progress session is still first and was not replaced.
    assert model["recent"][0]["is_in_progress"] is True
    # Attention rows are promoted into visible recent.
    assert attention_keys, "there must be attention rows"
    assert attention_keys <= recent_keys, "attention must be subset of recent"
    assert len(model["recent"]) == recent_limit
    # No duplicate rows in recent.
    assert len(recent_keys) == len(model["recent"])
    # The attention rows have earlier start times than the organized rows
    # that remain — they were promoted from beyond the truncation boundary.
    attention_start_times = {row["start_time"] for row in model["attention"]}
    organized_recent = [
        row for row in model["recent"]
        if row["projection_instance_key"] not in attention_keys
        and not row.get("is_in_progress")
    ]
    if organized_recent:
        newest_attention_start = max(attention_start_times)
        oldest_organized_start = min(
            row["start_time"] for row in organized_recent
        )
        assert newest_attention_start < oldest_organized_start, (
            "promoted attention rows must be older than remaining organized rows"
        )
    activity_service.close_activity(live_activity_id, f"{report_date} 12:30:00")


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
