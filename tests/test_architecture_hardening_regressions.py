from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.support.activity_factory import create_closed_activity, create_open_activity
from worktrace.api import timeline_api
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection, now_str
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.services import (
    database_maintenance_service,
    folder_rule_service,
    privacy_gate_service,
    project_service,
    report_revision_service,
    report_session_operation_service,
    rule_batch_service,
    rule_service,
    statistics_service,
    view_model_service,
)
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.statistics_projection import build_statistics_projection
from worktrace.webview_ui.bridge import WebViewBridge
from worktrace.write_gate import DATABASE_WRITE_GATE

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-15"


def _activity(start, end, *, project_id=None, status="normal", app="Word"):
    common = {
        "app_name": app,
        "process_name": app.lower() + ".exe",
        "window_title": app,
        "project_id": project_id,
        "status": status,
    }
    if end is None:
        return create_open_activity(
            start_time=f"{DATE} {start}",
            **common,
        )
    return create_closed_activity(
        day=DATE,
        start=start,
        end=end,
        **common,
    )


def test_clear_all_preserves_installation_privacy_and_runtime_intent(temp_db):
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
        "user_paused": "false",
        "collector_status": "stopped",
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
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        uow.connection.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )
    assert report_revision_service.get_report_structure_revision(DATE) != before


def test_structure_revision_tracks_resource_display_facts(temp_db):
    activity_id = _activity("09:00:00", None)
    before = report_revision_service.get_report_structure_revision(DATE)
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        uow.connection.execute(
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
