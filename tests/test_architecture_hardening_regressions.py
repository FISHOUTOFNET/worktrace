from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_service,
    database_maintenance_service,
    privacy_gate_service,
    project_service,
    report_revision_service,
    statistics_service,
    view_model_hardening_service,
)
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.statistics_projection import build_statistics_projection
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-15"


def _activity(start, end, *, project_id=None, status="normal", app="Word"):
    activity_id = activity_service.create_activity(
        app,
        app.lower() + ".exe",
        app,
        project_id=project_id,
        status=status,
        start_time=f"{DATE} {start}",
    )
    activity_service.finalize_created_activity(activity_id)
    if end is not None:
        activity_service.close_activity(activity_id, f"{DATE} {end}")
    return activity_id


def test_clear_all_preserves_installation_privacy_but_pauses_sensitive_runtime(temp_db):
    privacy_gate_service.accept_privacy_notice()
    project_service.create_project("Client")
    database_maintenance_service.clear_all_live_data()
    assert privacy_gate_service.is_privacy_notice_accepted() is True
    with get_connection() as conn:
        settings = {
            row["key"]: row["value"]
            for row in conn.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?, ?)",
                ("user_paused", "collector_status", "clipboard_capture_enabled"),
            ).fetchall()
        }
    assert settings == {
        "user_paused": "true",
        "collector_status": "paused",
        "clipboard_capture_enabled": "false",
    }


def test_structure_revision_ignores_open_duration_but_tracks_structure(temp_db):
    activity_id = _activity("09:00:00", None)
    before = report_revision_service.get_report_structure_revision(DATE)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = ?, updated_at = ? WHERE id = ?",
            (777, now_str(), activity_id),
        )
    assert report_revision_service.get_report_structure_revision(DATE) == before
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )
    assert report_revision_service.get_report_structure_revision(DATE) != before


def test_structure_revision_tracks_resource_display_facts(temp_db):
    activity_id = _activity("09:00:00", None)
    before = report_revision_service.get_report_structure_revision(DATE)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_resource SET display_name = ? WHERE activity_id = ?",
            ("Renamed.docx", activity_id),
        )
    assert report_revision_service.get_report_structure_revision(DATE) != before


def test_export_revision_is_exact_closed_record_revision(temp_db):
    project_id = project_service.create_project("Client")
    _activity("09:00:00", "09:30:00", project_id=project_id)
    first = build_statistics_projection(build_visible_snapshot(DATE, DATE))
    open_id = _activity("10:00:00", None, project_id=project_id)
    second = build_statistics_projection(build_visible_snapshot(DATE, DATE))
    assert second.export_revision == first.export_revision
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = ?, updated_at = ? WHERE id = ?",
            (3600, now_str(), open_id),
        )
    third = build_statistics_projection(build_visible_snapshot(DATE, DATE))
    assert third.export_revision == first.export_revision


def test_project_and_app_counts_exclude_privacy_and_uncategorized_buckets(temp_db):
    project_id = project_service.create_project("Client")
    _activity("09:00:00", "09:30:00", project_id=project_id)
    _activity("10:00:00", "10:10:00")
    _activity("11:00:00", "11:05:00", status="excluded", app="Secret")
    summary = statistics_service.get_statistics_export_summary(DATE, DATE)
    names = {row["display_name"] for row in summary["by_project"]}
    assert {"Client", "未归类", "已排除"}.issubset(names)
    assert summary["project_count"] == 1
    assert summary["app_count"] == 1
    assert {
        row["display_name"]
        for row in summary["by_project"]
        if row["is_concrete_project"]
    } == {"Client"}


def test_overview_counts_standalone_excluded_without_showing_it_in_recent(temp_db):
    _activity("11:00:00", "11:05:00", status="excluded", app="Secret")
    payload = view_model_hardening_service.get_overview_view_model(DATE)
    assert payload["today_total_seconds"] == 300
    assert all(
        str(row.get("row_kind") or "") != "standalone_status"
        for row in payload.get("activities") or []
    )


def test_persisted_open_session_allows_project_and_note_but_not_duration(temp_db):
    first_project = project_service.create_project("A")
    second_project = project_service.create_project("B")
    _activity("09:00:00", None, project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "open-project-note-edit",
        second_project,
        None,
        "open memo",
    )
    assert result["ok"] is True
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert updated["project_id"] == second_project
    assert updated["session_note"] == "open memo"
    with pytest.raises(Exception):
        timeline_api.save_timeline_session_edit(
            DATE,
            updated["projection_instance_key"],
            updated["projection_revision"],
            "open-duration-rejected",
            None,
            600,
            "open memo",
        )


def test_runtime_and_backup_facades_have_single_owners():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "worktrace/runtime/app_runtime.py").read_text(encoding="utf-8")
    backup_api = (root / "worktrace/api/backup_api.py").read_text(encoding="utf-8")
    assert "privacy_gate_service" not in runtime
    assert "capture_installation_privacy_state" not in backup_api
    assert "restore_installation_privacy_state" not in backup_api


def test_statistics_bridge_separates_display_summary_and_export_ticket(temp_db):
    summary = {
        "date_from": DATE,
        "date_to": DATE,
        "snapshot_revision": "snapshot-internal",
        "export_revision": "export-ticket-revision",
        "total_duration_seconds": 60,
        "project_duration_seconds": 60,
        "activity_count": 1,
        "session_count": 1,
        "export_row_count": 1,
        "project_count": 1,
        "app_count": 1,
        "by_project": [],
        "by_app": [],
        "by_status": [],
        "export_preview": {
            "date_from": DATE,
            "date_to": DATE,
            "snapshot_revision": "snapshot-internal",
            "export_revision": "export-ticket-revision",
            "included_activity_count": 1,
            "session_count": 1,
            "export_row_count": 1,
            "included_duration_seconds": 60,
            "available_formats": ["csv"],
            "export_actions_enabled": True,
        },
    }
    with patch(
        "worktrace.webview_ui.bridge_statistics.statistics_api.get_statistics_export_summary",
        return_value=summary,
    ):
        result = WebViewBridge().get_statistics_export_summary(DATE, DATE)
    assert set(result) == {"ok", "summary", "export_ticket"}
    assert result["export_ticket"] == {
        "date_from": DATE,
        "date_to": DATE,
        "revision": "export-ticket-revision",
    }
    serialized_summary = json.dumps(result["summary"], ensure_ascii=False)
    assert "snapshot-internal" not in serialized_summary
    assert "export-ticket-revision" not in serialized_summary


def test_frontend_generation_and_coalescing_contracts_are_shipping():
    root = Path(__file__).resolve().parents[1]
    request_state = (
        root / "worktrace/webview_ui/js/timeline_request_state.js"
    ).read_text(encoding="utf-8")
    init = (root / "worktrace/webview_ui/js/init.js").read_text(encoding="utf-8")
    statistics = (root / "worktrace/webview_ui/js/statistics.js").read_text(
        encoding="utf-8"
    )
    rules = (root / "worktrace/webview_ui/js/rules.js").read_text(encoding="utf-8")
    assert "bumpDataEpoch" in request_state
    assert "dataEpoch" in request_state
    assert "activePageRefreshPending" in init
    assert "resetClientGeneration" in init
    assert "statisticsAcceptedPayload" in statistics
    assert "statisticsLoadPromise" in statistics
    assert "exportRevision" in statistics
    assert "projectsLoadPromise" in rules
    assert "data-project-load-gate" in rules
    assert "stopImmediatePropagation" in rules
