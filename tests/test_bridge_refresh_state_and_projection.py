"""Bridge refresh contracts for the persisted-open display architecture."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from worktrace.constants import STATUS_NORMAL, TIME_FORMAT
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


def _set_snapshot(snapshot: dict | None) -> None:
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot) if snapshot else "")
    settings_service.clear_settings_cache()


def _snapshot(*, elapsed: int = 30, candidate: str = "Candidate", transition: dict | None = None) -> dict:
    return {
        "app_name": "App", "process_name": "app.exe", "status": STATUS_NORMAL,
        "start_time": (datetime.now() - timedelta(seconds=60)).strftime(TIME_FORMAT),
        "elapsed_seconds": elapsed, "extra_seconds": 0, "is_persisted": False,
        "persisted_activity_id": 0, "display_project": {"id": 1, "name": "Official"},
        "candidate_project": {"id": 2, "name": candidate}, "suggested_project_name": candidate,
        "inferred_project_name": candidate, "project_transition": transition or {"pending": True, "to_project_id": 2},
        "window_title": "SECRET_TITLE", "file_path_hint": "D:/secret.py", "clipboard": "SECRET_CLIPBOARD",
    }


def test_refresh_state_is_lightweight_and_display_safe(bridge):
    _set_snapshot(_snapshot())
    result = bridge.get_refresh_state()
    assert result["ok"] is True
    assert "snapshot_baseline_epoch_ms" not in result
    encoded = json.dumps(result)
    for secret in ("SECRET_TITLE", "SECRET_CLIPBOARD", "D:/secret.py"):
        assert secret not in encoded


def test_elapsed_only_change_does_not_refresh_but_status_does(bridge):
    first = _snapshot(elapsed=10)
    _set_snapshot(first)
    r1 = bridge.get_refresh_state()["refresh_revision"]
    _set_snapshot({**first, "elapsed_seconds": 90, "extra_seconds": 80})
    assert bridge.get_refresh_state()["refresh_revision"] == r1
    _set_snapshot({**first, "status": "idle"})
    assert bridge.get_refresh_state()["refresh_revision"] != r1


def test_candidate_and_transition_changes_do_not_refresh(bridge):
    first = _snapshot(candidate="Candidate A", transition={"pending": True, "to_project_id": 2})
    _set_snapshot(first)
    r1 = bridge.get_refresh_state()["refresh_revision"]
    _set_snapshot({**first, "candidate_project": {"id": 3, "name": "Candidate B"}, "suggested_project_name": "Candidate B", "inferred_project_name": "Candidate B", "project_transition": {"pending": False, "to_project_id": 3}})
    assert bridge.get_refresh_state()["refresh_revision"] == r1


def test_normal_unpersisted_snapshot_does_not_materialize_recent_or_timeline_rows(bridge):
    _set_snapshot(_snapshot())
    assert bridge.get_overview()["activities"] == []
    assert bridge.get_recent_activities()["activities"] == []
    assert bridge.get_timeline()["sessions"] == []
