"""Tests for the WebView bridge (worktrace.webview_ui.bridge).

The bridge must:
- return JSON-serializable dicts;
- never return tracebacks;
- only import worktrace.api (enforced by test_ui_backend_boundary.py).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from worktrace import db
from worktrace.services import settings_service
from worktrace.webview_ui.bridge import WebViewBridge


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    return WebViewBridge()


def test_get_status_returns_dict(bridge):
    result = bridge.get_status()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "status" in result
    assert "paused" in result
    assert "display" in result


def test_get_status_is_json_serializable(bridge):
    result = bridge.get_status()
    json.dumps(result)


def test_toggle_pause_returns_dict(bridge):
    result = bridge.toggle_pause()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "status" in result


def test_toggle_pause_is_json_serializable(bridge):
    result = bridge.toggle_pause()
    json.dumps(result)


def test_get_overview_returns_dict(bridge):
    result = bridge.get_overview()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "date" in result
    assert "total_duration" in result
    assert "classified_duration" in result
    assert "uncategorized_duration" in result
    assert "project_count" in result
    assert "current_activity" in result


def test_get_overview_is_json_serializable(bridge):
    result = bridge.get_overview()
    json.dumps(result)


def test_get_recent_activities_returns_dict_with_list(bridge):
    result = bridge.get_recent_activities()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert isinstance(result["activities"], list)


def test_get_recent_activities_is_json_serializable(bridge):
    result = bridge.get_recent_activities()
    json.dumps(result)


def test_get_timeline_returns_dict_with_sessions(bridge):
    result = bridge.get_timeline()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "date" in result
    assert "total_duration" in result
    assert "current_activity" in result
    assert isinstance(result["sessions"], list)


def test_get_timeline_is_json_serializable(bridge):
    result = bridge.get_timeline()
    json.dumps(result)


def test_get_timeline_with_explicit_date(bridge):
    from datetime import date as dt_date, timedelta

    today = dt_date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    result = bridge.get_timeline(yesterday)
    assert result["ok"] is True
    assert result["date"] == yesterday


def test_get_timeline_session_details_returns_dict(bridge):
    result = bridge.get_timeline_session_details([], None)
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert isinstance(result["activities"], list)
    assert result["activities"] == []


def test_get_timeline_session_details_is_json_serializable(bridge):
    result = bridge.get_timeline_session_details([], None)
    json.dumps(result)


def test_get_timeline_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.get_default_report_date",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_timeline()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_get_timeline_session_details_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.get_default_report_date",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_timeline_session_details([1], None)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_get_status_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge.settings_api.get_collector_status",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_status()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "traceback" not in str(result).lower()
    assert "boom" not in str(result)


def test_toggle_pause_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge.settings_api.get_collector_status",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.toggle_pause()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)


def test_get_overview_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.get_default_report_date",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_overview()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)


def test_get_recent_activities_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.get_default_report_date",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_recent_activities()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)


def test_toggle_pause_sets_paused_when_running(bridge):
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("user_paused", "false")
    result = bridge.toggle_pause()
    assert result["ok"] is True
    assert result["paused"] is True
    assert settings_service.get_bool_setting("user_paused") is True


def test_toggle_pause_resumes_when_paused(bridge):
    settings_service.set_setting("collector_status", "paused")
    settings_service.set_setting("user_paused", "true")
    result = bridge.toggle_pause()
    assert result["ok"] is True
    # toggle_pause clears user_paused; the collector thread updates
    # collector_status to "running" once it actually starts. Without a real
    # collector thread (test env), collector_status stays "paused", which
    # matches Tkinter behavior. Assert the user_paused flag was cleared.
    assert settings_service.get_bool_setting("user_paused") is False
