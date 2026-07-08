from __future__ import annotations

import json

import pytest

from tests.support.db_helpers import assign_activity_project
from worktrace.constants import STATUS_NORMAL, UNCATEGORIZED_PROJECT
from worktrace.services import (
    activity_service,
    project_service,
    settings_service,
    statistics_service,
    timeline_service,
)
from worktrace.services.activity_display_model_service import build_activity_display_model
from worktrace.services.live_display_service import compute_refresh_revision
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.contract, pytest.mark.db, pytest.mark.live_display]

TODAY = "2026-06-18"


@pytest.fixture()
def bridge(temp_db, monkeypatch) -> WebViewBridge:
    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: TODAY)
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("user_paused", "false")
    settings_service.clear_settings_cache()
    return WebViewBridge()


def _set_snapshot(snapshot: dict | None) -> None:
    settings_service.set_setting(
        "current_activity_snapshot", json.dumps(snapshot) if snapshot else ""
    )
    settings_service.clear_settings_cache()


def _pending_snapshot(
    *,
    name: str = "B",
    elapsed_seconds: int = 10,
    start: str = "09:02:10",
    display_project: dict | None = None,
    candidate_project: dict | None = None,
    project_transition: dict | None = None,
) -> dict:
    snapshot = {
        "app_name": name,
        "process_name": f"{name.lower()}.exe",
        "activity_display_name": name,
        "resource_display_name": name,
        "resource_identity_key": f"app:{name}",
        "inferred_project_name": name,
        "start_time": f"{TODAY} {start}",
        "elapsed_seconds": elapsed_seconds,
        "extra_seconds": 0,
        "status": STATUS_NORMAL,
        "is_persisted": False,
        "persisted_activity_id": 0,
    }
    if display_project is not None:
        snapshot["display_project"] = display_project
    if candidate_project is not None:
        snapshot["candidate_project"] = candidate_project
    if project_transition is not None:
        snapshot["project_transition"] = project_transition
    return snapshot


def _closed_anchor(seconds: int = 120) -> int:
    activity_id = activity_service.create_activity(
        "A",
        "a.exe",
        "A",
        start_time=f"{TODAY} 09:00:00",
    )
    activity_service.close_activity(activity_id, f"{TODAY} 09:02:00", seconds)
    return int(activity_id)


def test_borrowed_pending_timeline_details_total_conservation_during_grace_window(bridge):
    anchor_id = _closed_anchor(120)
    _set_snapshot(_pending_snapshot(elapsed_seconds=10))

    timeline = bridge.get_timeline(TODAY)
    details = bridge.get_timeline_session_details([anchor_id], TODAY)

    session = timeline["sessions"][0]
    assert session["duration_seconds"] == 130
    assert [row["duration_seconds"] for row in details["activities"]] == [120, 10]
    assert sum(row["duration_seconds"] for row in details["activities"]) == session[
        "duration_seconds"
    ]

    pending_detail = details["activities"][1]
    assert pending_detail["editable"] is False
    assert pending_detail["exportable"] is False
    assert pending_detail["display_only"] is True
    assert pending_detail["is_virtual"] is True
    assert pending_detail["is_virtual_live"] is True

    rows = activity_service.get_activities_by_date(TODAY)
    assert [int(row["id"]) for row in rows] == [anchor_id]
    assert rows[0]["duration_seconds"] == 120


def test_borrowed_pending_detail_row_uses_current_live_semantic(bridge):
    anchor_id = _closed_anchor(120)
    _set_snapshot(_pending_snapshot(elapsed_seconds=10))

    details = bridge.get_timeline_session_details([anchor_id], TODAY)
    live_clock = details["live_clock"]
    pending_detail = details["activities"][1]

    assert pending_detail["duration_semantic"] == "current_live"
    assert pending_detail["display_base_seconds"] == 0
    assert pending_detail["duration_seconds"] == 10
    assert pending_detail["live_delta_eligible"] is True
    assert pending_detail["display_span_id"] == live_clock["display_span_id"]
    assert pending_detail["stable_live_key_hash"] == live_clock["stable_live_key_hash"]
    assert pending_detail["source"] == "borrowed_anchor_pending"


def test_borrowed_anchor_uses_official_attribution_policy(bridge):
    anchor_id = _closed_anchor(120)
    project_id = project_service.create_project("ContextProject")
    assign_activity_project(anchor_id, project_id, manual=False)
    _set_snapshot(_pending_snapshot(elapsed_seconds=10))

    overview = bridge.get_overview()
    timeline = bridge.get_timeline(TODAY)
    details = bridge.get_timeline_session_details([anchor_id], TODAY)
    stats = statistics_service.get_summary(TODAY, TODAY)

    rows = [
        overview["activities"][0],
        timeline["sessions"][0],
        details["activities"][1],
    ]
    for row in rows:
        assert row["project_name"] == UNCATEGORIZED_PROJECT
        assert row["project_id"] == 0
        assert row["is_classified"] is False
        assert row["is_uncategorized"] is True
        assert row["display_project"]["name"] == UNCATEGORIZED_PROJECT
        assert row["candidate_project"]["name"] == ""
    assert stats["uncategorized_duration"] == 120


def test_attribution_only_change_does_not_reset_live_clock_revision(bridge):
    base_project = {
        "id": None,
        "name": UNCATEGORIZED_PROJECT,
        "description": "",
        "source": "uncategorized",
        "is_uncategorized": True,
        "is_suggested_project": False,
    }
    candidate_project = {
        "id": None,
        "name": "CandidateA",
        "description": "",
        "source": "suggested_project_name",
        "is_uncategorized": False,
        "is_suggested_project": True,
    }
    changed_candidate = dict(candidate_project, name="CandidateB")
    transition = {
        "pending": True,
        "started_at": f"{TODAY} 09:02:00",
        "elapsed_seconds": 10,
        "threshold_seconds": 30,
        "from_project_id": None,
        "to_project_id": 9,
    }
    changed_transition = dict(transition, to_project_id=10)
    snapshot_a = _pending_snapshot(
        display_project=base_project,
        candidate_project=candidate_project,
        project_transition=transition,
    )
    snapshot_b = _pending_snapshot(
        display_project=base_project,
        candidate_project=changed_candidate,
        project_transition=changed_transition,
    )

    model_a = build_activity_display_model(TODAY, TODAY, snapshot=snapshot_a)
    model_b = build_activity_display_model(TODAY, TODAY, snapshot=snapshot_b)
    _, debug_a = compute_refresh_revision(
        snapshot_a, "running", False, TODAY, TODAY, display_model=model_a
    )
    _, debug_b = compute_refresh_revision(
        snapshot_b, "running", False, TODAY, TODAY, display_model=model_b
    )

    assert model_a["live_clock"]["stable_live_key_hash"] == model_b["live_clock"][
        "stable_live_key_hash"
    ]
    assert debug_a["live_clock_revision"] == debug_b["live_clock_revision"]
    assert debug_a["display_projection_revision"] != debug_b[
        "display_projection_revision"
    ]


def test_overview_kpi_live_targets_are_backend_owned(bridge):
    _closed_anchor(120)
    _set_snapshot(_pending_snapshot(elapsed_seconds=10))

    overview = bridge.get_overview()

    assert "kpi_live_targets" in overview
    targets = overview["kpi_live_targets"]
    assert targets["today_total_seconds"] == {"enabled": True, "base_seconds": 120}
    assert targets["classified_seconds"]["enabled"] is False
    assert targets["uncategorized_seconds"] == {"enabled": True, "base_seconds": 120}
