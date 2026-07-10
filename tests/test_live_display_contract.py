"""Focused contracts shared by every persisted-open live surface."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from worktrace.constants import TIME_FORMAT
from worktrace.services import activity_service, settings_service
from worktrace.webview_ui.bridge import WebViewBridge


pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.live_display]


@pytest.fixture()
def bridge(temp_db):
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("user_paused", "false")
    settings_service.clear_settings_cache()
    return WebViewBridge()


def _set_snapshot(snapshot: dict) -> None:
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot))
    settings_service.clear_settings_cache()


def _persisted_snapshot(activity_id: int, start: str) -> dict:
    return {
        "app_name": "Code", "process_name": "code.exe", "status": "normal",
        "start_time": start, "elapsed_seconds": 30, "extra_seconds": 0,
        "is_persisted": True, "persisted_activity_id": activity_id,
        "display_project": {"id": None, "name": "未归类", "source": "uncategorized"},
    }


def test_persisted_open_has_one_shared_identity_across_view_models(bridge):
    start = (datetime.now() - timedelta(seconds=30)).strftime(TIME_FORMAT)
    activity_id = activity_service.create_activity("Code", "code.exe", "main.py", start_time=start)
    _set_snapshot(_persisted_snapshot(activity_id, start))

    overview, recent, timeline = bridge.get_overview(), bridge.get_recent_activities(), bridge.get_timeline()
    expected = overview["live_clock"]["stable_live_key_hash"]
    assert overview["live_clock"]["live_state"] == "persisted_open"
    assert recent["live_clock"]["stable_live_key_hash"] == expected
    assert timeline["live_clock"]["stable_live_key_hash"] == expected
    recent_row = next(row for row in recent["activities"] if row.get("activity_id") == activity_id)
    assert recent_row["stable_live_key_hash"] == expected


def test_persisted_open_natural_time_growth_does_not_change_refresh_revision(bridge):
    start = (datetime.now() - timedelta(seconds=30)).strftime(TIME_FORMAT)
    activity_id = activity_service.create_activity("Code", "code.exe", "main.py", start_time=start)
    snapshot = _persisted_snapshot(activity_id, start)
    _set_snapshot(snapshot)
    first = bridge.get_refresh_state()["refresh_revision"]
    _set_snapshot({**snapshot, "elapsed_seconds": 90, "extra_seconds": 60})
    assert bridge.get_refresh_state()["refresh_revision"] == first


def test_live_overlay_does_not_write_the_activity_row(bridge):
    start = (datetime.now() - timedelta(seconds=30)).strftime(TIME_FORMAT)
    activity_id = activity_service.create_activity("Code", "code.exe", "main.py", start_time=start)
    _set_snapshot(_persisted_snapshot(activity_id, start))
    before = dict(activity_service.get_activity(activity_id))
    bridge.get_overview(); bridge.get_recent_activities(); bridge.get_timeline()
    after = activity_service.get_activity(activity_id)
    assert after["duration_seconds"] == before["duration_seconds"]
    assert after["end_time"] == before["end_time"]
