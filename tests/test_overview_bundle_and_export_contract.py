"""Overview and report surface contracts for current live semantics."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from worktrace.constants import TIME_FORMAT
from worktrace.services import settings_service
from worktrace.webview_ui.bridge import WebViewBridge


pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.live_display]


@pytest.fixture()
def bridge(temp_db):
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("user_paused", "false")
    settings_service.clear_settings_cache()
    return WebViewBridge()


def _snapshot() -> dict:
    return {
        "app_name": "App", "process_name": "app.exe", "status": "normal",
        "start_time": (datetime.now() - timedelta(seconds=10)).strftime(TIME_FORMAT),
        "elapsed_seconds": 10, "is_persisted": False, "persisted_activity_id": 0,
        "display_project": {"id": 1, "name": "Official"},
        "candidate_project": {"id": 2, "name": "Candidate"},
        "suggested_project_name": "Candidate", "window_title": "SECRET_TITLE",
    }


def test_overview_bundle_is_display_safe_and_has_the_current_payload_shape(bridge):
    settings_service.set_setting("current_activity_snapshot", json.dumps(_snapshot()))
    settings_service.clear_settings_cache()
    bundle = bridge.get_overview()
    assert bundle["ok"] is True
    for key in ("live_clock", "current_activity", "activities", "sample_id"):
        assert key in bundle
    assert "SECRET_TITLE" not in json.dumps(bundle)


def test_normal_unpersisted_snapshot_is_absent_from_overview_timeline_and_details(bridge):
    settings_service.set_setting("current_activity_snapshot", json.dumps(_snapshot()))
    settings_service.clear_settings_cache()
    assert bridge.get_overview()["activities"] == []
    assert bridge.get_timeline()["sessions"] == []
    assert bridge.get_timeline_session_details([], None)["activities"] == []
