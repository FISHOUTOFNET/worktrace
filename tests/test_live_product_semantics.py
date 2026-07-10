"""Small end-to-end contracts for the current collector and live product."""

from __future__ import annotations

import json

import pytest

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, settings_service, timeline_service
from worktrace.webview_ui.bridge import WebViewBridge


pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.live_display]
DATE = "2026-06-18"


def _window(title: str) -> ActiveWindow:
    return ActiveWindow(title, f"{title}.exe", title)


def _rows() -> list[dict]:
    return sorted(activity_service.get_activities_by_date(DATE), key=lambda row: row["start_time"])


def test_fresh_normal_activity_immediately_owns_a_persisted_open_row(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _window("A"), at_time=f"{DATE} 09:00:00")

    rows = _rows()
    snapshot = json.loads(settings_service.get_setting("current_activity_snapshot", "{}") or "{}")
    assert len(rows) == 1 and rows[0]["end_time"] is None
    assert snapshot["persisted_activity_id"] == rows[0]["id"]
    assert WebViewBridge().get_overview()["live_clock"]["live_state"] == "persisted_open"


def test_window_switch_closes_its_own_row_and_never_reopens_an_anchor(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _window("A"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("recording", _window("B"), at_time=f"{DATE} 09:00:05")
    machine.transition_to("recording", _window("A"), at_time=f"{DATE} 09:00:10")
    machine.transition_to("stopped", at_time=f"{DATE} 09:00:20")

    rows = _rows()
    assert [row["window_title"] for row in rows] == ["A", "B", "A"]
    assert [row["duration_seconds"] for row in rows] == [5, 5, 10]
    assert rows[0]["end_time"] == f"{DATE} 09:00:05"


def test_pause_is_a_hard_collector_boundary(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _window("A"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("paused", at_time=f"{DATE} 09:00:10")
    machine.transition_to("recording", _window("B"), at_time=f"{DATE} 09:00:20")

    rows = _rows()
    normal_rows = [row for row in rows if row["window_title"] in {"A", "B"}]
    assert [row["window_title"] for row in normal_rows] == ["A", "B"]
    assert normal_rows[0]["end_time"] == f"{DATE} 09:00:10"
    assert normal_rows[1]["end_time"] is None


def test_stop_and_restart_do_not_restore_stale_snapshot_metadata(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _window("A"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("stopped", at_time=f"{DATE} 09:00:05")
    machine.transition_to("recording", _window("B"), at_time=f"{DATE} 09:00:10")

    snapshot = json.loads(settings_service.get_setting("current_activity_snapshot", "{}") or "{}")
    assert snapshot["persisted_activity_id"] == _rows()[-1]["id"]
    assert snapshot.get("window_title") == "B"
