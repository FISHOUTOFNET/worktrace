from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.db_helpers import assign_activity_project
from worktrace.constants import STATUS_NORMAL, UNCATEGORIZED_PROJECT
from worktrace.services import (
    activity_service,
    project_service,
    settings_service,
    timeline_service,
)
from worktrace.services.activity_display_model_service import build_activity_display_model
from worktrace.services.live_display_service import (
    build_current_activity_summary,
    classify_live_state,
    compute_refresh_revision,
)
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


def test_normal_snapshot_without_persisted_open_row_fails_closed(bridge):
    anchor_id = _closed_anchor(120)
    _set_snapshot(_pending_snapshot(elapsed_seconds=10))

    snapshot = _pending_snapshot(elapsed_seconds=10)
    model = build_activity_display_model(TODAY, TODAY, snapshot=snapshot)
    overview = bridge.get_overview()
    timeline = bridge.get_timeline(TODAY)
    details = bridge.get_timeline_session_details([anchor_id], TODAY)

    assert classify_live_state(snapshot) == "none"
    assert model["display_spans"] == []
    assert model["live_clock"]["live_state"] == "none"
    session = timeline["sessions"][0]
    assert session["duration_seconds"] == 120
    assert [row["duration_seconds"] for row in details["activities"]] == [120]
    assert all(row.get("source") != "borrowed_anchor" for row in details["activities"])
    assert not any(row.get("is_virtual_live") for row in overview["activities"])

    rows = activity_service.get_activities_by_date(TODAY)
    assert [int(row["id"]) for row in rows] == [anchor_id]
    assert rows[0]["duration_seconds"] == 120


def test_persisted_open_snapshot_projects_only_its_own_row(bridge):
    anchor_id = _closed_anchor(120)
    project_id = project_service.create_project("ContextProject")
    open_id = activity_service.create_activity(
        "B", "b.exe", "B", start_time=f"{TODAY} 09:02:10"
    )
    assign_activity_project(open_id, project_id, manual=False)
    snapshot = _pending_snapshot(
        elapsed_seconds=10,
        display_project={
            "id": project_id,
            "name": "ContextProject",
            "description": "",
            "source": "manual",
            "is_uncategorized": False,
            "is_suggested_project": False,
        },
    )
    snapshot.update({"is_persisted": True, "persisted_activity_id": open_id})

    model = build_activity_display_model(TODAY, TODAY, snapshot=snapshot)
    span = model["display_spans"][0]

    assert classify_live_state(snapshot) == "persisted_open"
    assert span["activity_id"] == open_id
    assert span["anchor_activity_id"] == open_id
    assert span["duration_seconds"] == 10
    assert span["project_name"] == "ContextProject"
    assert anchor_id != span["anchor_activity_id"]


def test_virtual_snapshot_without_display_project_does_not_leak_inferred_project():
    snapshot = {
        "app_name": "Code",
        "process_name": "code.exe",
        "activity_display_name": "main.py",
        "resource_display_name": "main.py",
        "resource_identity_key": "app:code",
        "status": STATUS_NORMAL,
        "start_time": f"{TODAY} 09:00:00",
        "elapsed_seconds": 10,
        "is_persisted": False,
        "persisted_activity_id": None,
        "inferred_project_name": "LeakedRawProject",
    }

    summary = build_current_activity_summary(snapshot, report_date=TODAY, today=TODAY)
    model = build_activity_display_model(TODAY, TODAY, snapshot=snapshot)
    current = model["current_activity"]

    assert summary["project_name"] == UNCATEGORIZED_PROJECT
    assert current["project_name"] == UNCATEGORIZED_PROJECT
    assert current["display_project"]["name"] == UNCATEGORIZED_PROJECT
    assert current["is_classified"] is False
    assert current["is_uncategorized"] is True
    assert "LeakedRawProject" not in current["display"]
    assert "LeakedRawProject" not in str(current["display_project"])
    assert "LeakedRawProject" not in str(model.get("display_spans") or [])


def test_candidate_project_does_not_participate_in_revision_or_signature(bridge):
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
    assert debug_a["display_projection_revision"] == debug_b["display_projection_revision"]
    assert debug_a["refresh_revision"] == debug_b["refresh_revision"]
    assert model_a["display_structural_signature"] == model_b["display_structural_signature"]
    assert "CandidateA" not in model_a["display_structural_signature"]
    assert "CandidateB" not in model_b["display_structural_signature"]


def test_production_structural_changes_update_display_projection_revision():
    project_a = {"id": 1, "name": "Project A", "source": "manual"}
    project_b = {"id": 2, "name": "Project B", "source": "manual"}
    base = _pending_snapshot(display_project=project_a)
    base.update({"is_persisted": True, "persisted_activity_id": 101})
    changed = dict(base, display_project=project_b, persisted_activity_id=102)
    model_a = build_activity_display_model(TODAY, TODAY, snapshot=base)
    model_b = build_activity_display_model(TODAY, TODAY, snapshot=changed)
    _, debug_a = compute_refresh_revision(base, "running", False, TODAY, TODAY, display_model=model_a)
    _, debug_b = compute_refresh_revision(changed, "running", False, TODAY, TODAY, display_model=model_b)

    assert debug_a["display_projection_revision"] != debug_b["display_projection_revision"]
    assert debug_a["refresh_revision"] != debug_b["refresh_revision"]


def test_frontend_runtime_identity_excludes_candidate_project():
    source = (Path(__file__).resolve().parents[1] / "worktrace/webview_ui/js/core.js").read_text(encoding="utf-8")
    start = source.index("function runtimeVisualContinuityKey")
    end = source.index("App.runtimeVisualContinuityKey", start)
    runtime_key = source[start:end]
    assert "candidate_project" not in runtime_key
    assert "suggested_project_name" not in runtime_key

    init_source = (Path(__file__).resolve().parents[1] / "worktrace/webview_ui/js/init.js").read_text(encoding="utf-8")
    start = init_source.index("function currentActivityRenderIdentity")
    end = init_source.index("function refreshCurrentActivityFromState", start)
    render_identity = init_source[start:end]
    assert "candidate_project" not in render_identity
    assert "suggested_project_name" not in render_identity


def test_overview_kpi_live_targets_are_backend_owned(bridge):
    _closed_anchor(120)
    _set_snapshot(_pending_snapshot(elapsed_seconds=10))

    overview = bridge.get_overview()

    assert "kpi_live_targets" in overview
    targets = overview["kpi_live_targets"]
    assert targets["today_total_seconds"] == {"enabled": False, "base_seconds": 0}
    assert targets["classified_seconds"]["enabled"] is False
    assert targets["uncategorized_seconds"] == {"enabled": False, "base_seconds": 0}
