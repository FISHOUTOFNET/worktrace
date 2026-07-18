"""Collector raw-activity contract.

Short segments are no longer buffered, merged, dropped, or borrowed by the
collector. Any noise reduction is a read-only report projection concern.
"""

from __future__ import annotations
from tests.support import runtime_state_fixture

import json

import pytest

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, settings_service
from worktrace.services.project_ownership_service import (
    ProjectLabel,
    begin_ownership_for_new_resource,
)
from worktrace.services.report_projection_snapshot_service import get_report_sessions_by_date
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.collector_runtime, pytest.mark.integration, pytest.mark.db]

DATE = "2026-06-18"


def _normal(title: str) -> ActiveWindow:
    return ActiveWindow(title, f"{title.lower()}.exe", title)


def _rows() -> list[dict]:
    return sorted(activity_service.get_activities_by_date(DATE), key=lambda row: row["start_time"])


def _snapshot() -> dict:
    return json.loads(runtime_state_fixture.get_setting("current_activity_snapshot", "") or "{}")


def test_new_activity_persists_immediately(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time=f"{DATE} 09:00:00")
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["window_title"] == "A"
    assert rows[0]["end_time"] is None
    assert _snapshot()["is_persisted"] is True
    assert _snapshot()["persisted_activity_id"] == rows[0]["id"]
    assert WebViewBridge().get_overview()["live_clock"]["live_state"] == "persisted_open"


def test_switch_under_30_creates_separate_raw_rows(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("recording", _normal("B"), at_time=f"{DATE} 09:01:00")
    machine.transition_to("recording", _normal("C"), at_time=f"{DATE} 09:01:20")
    rows = _rows()
    assert [row["window_title"] for row in rows] == ["A", "B", "C"]
    assert rows[0]["duration_seconds"] == 60
    assert rows[1]["duration_seconds"] == 20
    assert rows[2]["end_time"] is None


def test_switch_back_to_same_resource_does_not_reopen_anchor(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("recording", _normal("B"), at_time=f"{DATE} 09:01:00")
    machine.transition_to("recording", _normal("A"), at_time=f"{DATE} 09:01:20")
    machine.transition_to("stopped", at_time=f"{DATE} 09:01:30")
    rows = _rows()
    assert [row["window_title"] for row in rows] == ["A", "B", "A"]
    assert [row["duration_seconds"] for row in rows] == [60, 20, 10]
    assert rows[0]["end_time"] == f"{DATE} 09:01:00"


def test_initial_short_activity_is_persisted(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("B"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("stopped", at_time=f"{DATE} 09:00:20")
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["window_title"] == "B"
    assert rows[0]["duration_seconds"] == 20


def test_no_pending_short_runtime_state_written(temp_db, monkeypatch):
    writes: list[tuple[str, str]] = []
    original = settings_service.set_setting

    def record_write(key: str, value: str) -> None:
        writes.append((key, value))
        original(key, value)

    monkeypatch.setattr(settings_service, "set_setting", record_write)
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("recording", _normal("B"), at_time=f"{DATE} 09:00:05")
    assert all(key not in {"pending_short_seconds", "pending_short_carry_provenance"} for key, _ in writes)


def test_live_display_uses_the_persisted_open_state(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time=f"{DATE} 09:00:00")
    overview = WebViewBridge().get_overview()
    assert overview["live_clock"]["live_state"] == "persisted_open"
    assert overview["current_activity"]["live_state"] == "persisted_open"


def test_report_projection_can_group_without_mutating_raw(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time=f"{DATE} 09:00:00")
    machine.transition_to("recording", _normal("B"), at_time=f"{DATE} 09:00:05")
    machine.transition_to("stopped", at_time=f"{DATE} 09:00:10")
    before = [(r["id"], r["start_time"], r["end_time"], r["duration_seconds"]) for r in _rows()]
    get_report_sessions_by_date(DATE)
    after = [(r["id"], r["start_time"], r["end_time"], r["duration_seconds"]) for r in _rows()]
    assert after == before


def test_project_display_official_only_without_30s_inheritance(temp_db):
    official = ProjectLabel(name="Rules", id=8, source="keyword_rule")
    official_state = begin_ownership_for_new_resource(official)
    assert official_state.display_project == official

    suggested = ProjectLabel(
        name="Suggested", source="suggested_project_name", is_suggested_project=True
    )
    suggested_state = begin_ownership_for_new_resource(suggested)
    assert suggested_state.display_project.is_uncategorized is True
    assert suggested_state.candidate_project == suggested
