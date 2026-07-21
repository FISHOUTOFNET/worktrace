from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from tests.support.application import build_test_bridge
from worktrace.services import project_service
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.db, pytest.mark.integration]


def test_timeline_bridge_returns_entries_and_snapshot_revision(temp_db):
    day = "2026-07-05"
    project = project_service.create_project("P")
    aid = activity_service.create_activity("App", "app.exe", "A", project_id=project, start_time=f"{day} 09:00:00")
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} 09:10:00")
    result = build_test_bridge().get_timeline(day)
    assert result["ok"] is True
    assert len(result["entries"]) == 1
    assert result["snapshot_revision"]
    assert "sessions" not in result


def test_projection_details_bridge_returns_actual_revision(temp_db):
    day = "2026-07-05"
    project = project_service.create_project("P")
    aid = activity_service.create_activity("App", "app.exe", "A", project_id=project, start_time=f"{day} 09:00:00")
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} 09:10:00")
    bridge = build_test_bridge()
    entry = bridge.get_timeline(day)["entries"][0]
    details = bridge.get_timeline_session_activity_summary(
        entry["projection_instance_key"], day, entry["projection_revision"]
    )
    assert details["resolved_projection_revision"] == entry["projection_revision"]


def test_bridge_error_protocol_separates_code_and_message():
    result = build_test_bridge().get_timeline_session_activity_summary("", "bad-date", "")
    assert result == {"ok": False, "error": "invalid_input", "message": "日期无效"}


def test_legacy_activity_details_bridge_is_absent():
    assert not hasattr(WebViewBridge, "get_timeline_session_details")
