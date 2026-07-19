"""Boundary contracts: normal rows belong to their own persisted activity."""

from __future__ import annotations
from tests.support import runtime_state_fixture
from tests.support.application import build_test_bridge

import json
import pytest

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, settings_service

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.live_display]
DATE = "2026-06-18"


def _window(title: str) -> ActiveWindow:
    return ActiveWindow(title, f"{title}.exe", title)


def test_collector_switch_creates_a_new_open_row_without_carrying_the_prior_row(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _window("A"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("recording", _window("B"), at_time=f"{DATE} 09:00:10")
    rows = sorted(activity_service.get_activities_by_date(DATE), key=lambda row: row["start_time"])
    assert [row["window_title"] for row in rows] == ["A", "B"]
    assert rows[0]["end_time"] == f"{DATE} 09:00:10"
    assert rows[1]["end_time"] is None


def test_pause_snapshot_is_static_and_has_no_normal_live_overlay(temp_db):
    runtime_state_fixture.set_setting(
        "current_activity_snapshot",
        json.dumps({"status": "paused", "elapsed_seconds": 10}),
    )
    settings_service.set_setting("collector_status", "paused")
    settings_service.clear_settings_cache()

    overview = build_test_bridge().get_overview()

    assert overview["runtime"]["clock"]["duration_semantic"] == "static_closed"
    assert overview["runtime"]["clock"]["live_state"] == "none"
    assert "live_clock" not in overview["runtime"]["current_activity"]
