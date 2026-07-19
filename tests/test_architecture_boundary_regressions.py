from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.support.activity_factory import create_closed_activity
from worktrace.services import view_model_service
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-15"


def test_overview_counts_standalone_excluded_without_showing_it_in_recent(temp_db):
    create_closed_activity(
        day=DATE,
        start="11:00:00",
        end="11:05:00",
        app_name="Secret",
        process_name="secret.exe",
        window_title="Secret",
        status="excluded",
    )

    payload = view_model_service.get_overview_view_model(DATE)

    assert payload["today_total_seconds"] == 300
    assert all(
        str(row.get("row_kind") or "") != "standalone_status"
        for row in payload.get("activities") or []
    )


def test_runtime_and_backup_facades_have_single_owners():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "worktrace/runtime/app_runtime.py").read_text(encoding="utf-8")
    backup_api = (root / "worktrace/api/backup_api.py").read_text(encoding="utf-8")

    assert "privacy_gate_service" not in runtime
    assert "capture_installation_privacy_state" not in backup_api
    assert "restore_installation_privacy_state" not in backup_api


def test_statistics_bridge_separates_display_summary_and_export_ticket(temp_db):
    envelope = {
        "summary": {
            "date_from": DATE,
            "date_to": DATE,
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
        },
        "export_ticket": {
            "date_from": DATE,
            "date_to": DATE,
            "revision": "export-ticket-revision",
        },
    }
    with patch(
        "worktrace.webview_ui.bridge_statistics.statistics_api.get_statistics_export_view_model",
        return_value=envelope,
    ):
        result = WebViewBridge().get_statistics_export_summary(DATE, DATE)

    assert set(result) == {"ok", "summary", "export_ticket"}
    assert result["export_ticket"] == envelope["export_ticket"]
    serialized_summary = json.dumps(result["summary"], ensure_ascii=False)
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
