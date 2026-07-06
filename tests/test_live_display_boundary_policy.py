from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.live_display]

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import (
    SOURCE_AUTO,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, session_boundary_service, settings_service
from worktrace.services.activity_display_model_service import build_activity_display_model
from worktrace.services.live_display_service import compute_refresh_revision
from worktrace.webview_ui.bridge import WebViewBridge
from tests.support.snapshot_factory import normal_snapshot


TODAY = "2026-06-18"


@pytest.fixture()
def bridge(temp_db, monkeypatch):
    from worktrace.services import timeline_service

    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: TODAY)
    settings_service.clear_settings_cache()
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("user_paused", "false")
    settings_service.clear_settings_cache()
    return WebViewBridge()


def _set_snapshot(snapshot: dict | None) -> None:
    settings_service.set_setting(
        "current_activity_snapshot", json.dumps(snapshot) if snapshot else ""
    )
    settings_service.clear_settings_cache()


def _write_legacy_pending_short_carry(
    seconds: int,
    *,
    source_start_time: str,
    source_end_time: str,
) -> None:
    settings_service.set_setting("pending_short_seconds", str(max(0, int(seconds))))
    settings_service.set_setting(
        "pending_short_carry_provenance",
        json.dumps(
            {
                "version": 1,
                "source_status": STATUS_NORMAL,
                "source_start_time": source_start_time,
                "source_end_time": source_end_time,
                "latest_boundary_at_write": session_boundary_service.latest_boundary_time() or "",
            },
            sort_keys=True,
        ),
    )
    settings_service.clear_settings_cache()


def _snapshot(
    *,
    elapsed_seconds: int,
    start_time: str = f"{TODAY} 09:00:00",
    status: str = STATUS_NORMAL,
    is_persisted: bool = False,
    persisted_activity_id: int = 0,
    extra_seconds: int = 0,
    window_title: str = "Window",
) -> dict:
    return normal_snapshot(
        elapsed_seconds=elapsed_seconds,
        start_time=start_time,
        status=status,
        is_persisted=is_persisted,
        persisted_activity_id=persisted_activity_id,
        extra_seconds=extra_seconds,
        inferred_project_name="BoundaryProject",
        window_title=window_title,
    )


def _normal(title: str) -> ActiveWindow:
    return ActiveWindow(title, f"{title.lower()}.exe", title)


def test_current_only_pending_base_zero_no_stale_carry(bridge):
    _set_snapshot(_snapshot(elapsed_seconds=12, extra_seconds=7))

    model = build_activity_display_model(report_date=TODAY, today=TODAY)
    clock = model["live_clock"]
    assert clock["display_session_kind"] == "current_only_pending"
    assert clock["base_policy"] == "current_only_zero"
    assert clock["display_base_seconds"] == 0
    assert clock["duration_seconds_at_sample"] == 12
    assert model["current_activity"]["elapsed_seconds"] == 12
    assert model["display_spans"] == []

    overview = bridge.get_overview()
    timeline = bridge.get_timeline(TODAY)
    details = bridge.get_timeline_session_details([0], TODAY)
    assert overview["current_activity"]["elapsed_seconds"] == 12
    assert overview["activities"] == []
    assert overview["today_total_seconds"] == 0
    assert timeline["sessions"] == []
    assert details["activities"] == []


def test_current_only_pending_ignores_stale_pending_after_pause_or_restart(bridge):
    _write_legacy_pending_short_carry(
        20,
        source_start_time=f"{TODAY} 08:59:00",
        source_end_time=f"{TODAY} 08:59:20",
    )
    session_boundary_service.record_boundary(f"{TODAY} 09:00:00", "paused")
    _set_snapshot(
        _snapshot(elapsed_seconds=5, start_time=f"{TODAY} 09:01:00", extra_seconds=9)
    )

    model = build_activity_display_model(report_date=TODAY, today=TODAY)
    clock = model["live_clock"]
    assert clock["display_session_kind"] == "current_only_pending"
    assert clock["base_policy"] == "current_only_zero"
    assert clock["display_base_seconds"] == 0
    assert clock["duration_seconds_at_sample"] == 5

    overview = bridge.get_overview()
    timeline = bridge.get_timeline(TODAY)
    assert overview["current_activity"]["elapsed_seconds"] == 5
    assert overview["activities"] == []
    assert timeline["sessions"] == []


def test_current_only_pending_base_zero_after_dropped_short(bridge):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("Short"), at_time=f"{TODAY} 09:00:00")
    machine.transition_to("recording", _normal("Next"), at_time=f"{TODAY} 09:00:20")
    machine.transition_to("recording", _normal("Next"), at_time=f"{TODAY} 09:00:25")

    model = build_activity_display_model(report_date=TODAY, today=TODAY)
    clock = model["live_clock"]
    assert clock["display_session_kind"] == "current_only_pending"
    assert clock["base_policy"] == "current_only_zero"
    assert clock["display_base_seconds"] == 0
    assert clock["duration_seconds_at_sample"] == 5
    assert model["current_activity"]["elapsed_seconds"] == 5

    overview = bridge.get_overview()
    assert overview["current_activity"]["elapsed_seconds"] == 5
    assert overview["activities"] == []


def test_invalid_pending_never_folded_into_persisted_open_extra(temp_db):
    settings_service.set_setting("pending_short_seconds", "20")
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("Persisted"), at_time=f"{TODAY} 09:00:00")
    machine.transition_to("recording", _normal("Persisted"), at_time=f"{TODAY} 09:00:31")

    snapshot = json.loads(settings_service.get_setting("current_activity_snapshot", "") or "{}")
    assert snapshot["is_persisted"] is True
    assert int(snapshot["extra_seconds"]) == 0
    assert settings_service.get_setting("pending_short_seconds") == "0"
    row = activity_service.get_activity(int(snapshot["persisted_activity_id"]))
    assert int(row["duration_seconds"]) == 31


def test_persisted_open_preserves_aggregate_base(bridge):
    aid = activity_service.create_activity(
        "App",
        "app.exe",
        "Open",
        source=SOURCE_AUTO,
        start_time=f"{TODAY} 09:00:00",
    )
    activity_service.set_activity_duration(aid, 45)
    _set_snapshot(
        _snapshot(
            elapsed_seconds=15,
            start_time=f"{TODAY} 09:00:00",
            is_persisted=True,
            persisted_activity_id=aid,
            extra_seconds=30,
        )
    )

    model = build_activity_display_model(report_date=TODAY, today=TODAY)
    clock = model["live_clock"]
    assert clock["display_session_kind"] == "persisted_open"
    assert clock["base_policy"] == "persisted_extra"
    assert clock["display_base_seconds"] == 30
    assert clock["duration_seconds_at_sample"] == 45
    assert model["current_activity"]["elapsed_seconds"] == 15

    overview = bridge.get_overview()
    recent = next(r for r in overview["activities"] if int(r.get("activity_id") or 0) == aid)
    assert recent["display_base_seconds"] == 30
    assert recent["duration_seconds"] == 45


def test_running_pending_borrows_anchor_without_db_write(bridge):
    anchor_id = activity_service.create_activity(
        "App",
        "app.exe",
        "Anchor",
        source=SOURCE_AUTO,
        start_time=f"{TODAY} 09:00:00",
    )
    activity_service.close_activity(anchor_id, f"{TODAY} 09:01:00", 60)
    before = activity_service.get_activity(anchor_id)["duration_seconds"]
    _set_snapshot(
        _snapshot(
            elapsed_seconds=7,
            start_time=f"{TODAY} 09:01:00",
            window_title="Pending",
        )
    )

    model = build_activity_display_model(report_date=TODAY, today=TODAY)
    clock = model["live_clock"]
    assert clock["live_state"] == "borrowed_anchor_pending"
    assert clock["display_session_kind"] == "borrowed_anchor_pending"
    assert clock["base_policy"] == "borrowed_anchor_static"
    assert clock["display_base_seconds"] == 60
    assert clock["duration_seconds_at_sample"] == 67
    assert model["current_activity"]["elapsed_seconds"] == 7
    assert activity_service.get_activity(anchor_id)["duration_seconds"] == before

    overview = bridge.get_overview()
    recent = overview["activities"][0]
    assert int(recent.get("activity_id") or 0) == anchor_id
    assert recent["source"] == "borrowed_anchor_pending"
    assert recent["duration_seconds"] == 67
    assert recent["display_base_seconds"] == 60


@pytest.mark.parametrize("status", [STATUS_PAUSED, STATUS_IDLE, STATUS_EXCLUDED, STATUS_ERROR])
def test_paused_idle_excluded_error_status_only(temp_db, monkeypatch, status):
    from worktrace.services import timeline_service

    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: TODAY)
    _set_snapshot(_snapshot(elapsed_seconds=11, status=status))
    model = build_activity_display_model(report_date=TODAY, today=TODAY)

    assert model["live_clock"]["display_session_kind"] == "status_only"
    assert model["live_clock"]["project_duration_live"] is False
    assert model["live_clock"]["current_duration_live"] is False
    assert model["display_spans"] == []
    assert model["status_display_item"]["row_kind"] == "status_only"
    assert model["status_display_item"]["contributes_to_totals"] is False


def test_pause_fallback_clears_or_invalidates_pending(temp_db, monkeypatch):
    from worktrace.api import app_api

    monkeypatch.setattr("worktrace.api.app_api._runtime", None)
    settings_service.set_setting("pending_short_seconds", "17")
    settings_service.set_setting("current_activity_snapshot", '{"status":"normal"}')

    result = app_api.pause_collection_now()

    assert result == {"ok": False, "pause_pending": True}
    assert settings_service.get_setting("user_paused") == "true"
    assert settings_service.get_setting("pending_short_seconds") == "0"
    assert settings_service.get_setting("current_activity_snapshot") == ""
    assert session_boundary_service.latest_boundary_time() is not None


def test_historical_date_suppresses_live_clock(temp_db, monkeypatch):
    from worktrace.services import timeline_service

    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: TODAY)
    _set_snapshot(_snapshot(elapsed_seconds=30))
    model = build_activity_display_model(
        report_date="2026-06-17",
        today=TODAY,
    )
    clock = model["live_clock"]
    assert clock["live_state"] == "none"
    assert clock["display_span_id"] == ""
    assert clock["live_started_at_epoch_ms"] == 0
    assert clock["project_duration_live"] is False
    assert model["display_spans"] == []


def test_refresh_revision_changes_on_base_policy_change_but_not_natural_seconds(temp_db, monkeypatch):
    from worktrace.services import timeline_service

    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: TODAY)
    snapshot = _snapshot(elapsed_seconds=5, start_time=f"{TODAY} 09:00:20")
    model = build_activity_display_model(report_date=TODAY, today=TODAY, snapshot=snapshot)
    rev_fresh, _ = compute_refresh_revision(
        snapshot, "running", False, TODAY, report_date=TODAY, display_model=model
    )

    snapshot_tick = dict(snapshot, elapsed_seconds=6)
    model_tick = build_activity_display_model(
        report_date=TODAY, today=TODAY, snapshot=snapshot_tick
    )
    rev_tick, _ = compute_refresh_revision(
        snapshot_tick, "running", False, TODAY, report_date=TODAY, display_model=model_tick
    )
    assert rev_tick == rev_fresh

    _write_legacy_pending_short_carry(
        20,
        source_start_time=f"{TODAY} 09:00:00",
        source_end_time=f"{TODAY} 09:00:20",
    )
    model_continuous = build_activity_display_model(
        report_date=TODAY, today=TODAY, snapshot=snapshot_tick
    )
    rev_continuous, _ = compute_refresh_revision(
        snapshot_tick,
        "running",
        False,
        TODAY,
        report_date=TODAY,
        display_model=model_continuous,
    )
    assert rev_continuous == rev_fresh

    _write_legacy_pending_short_carry(
        21,
        source_start_time=f"{TODAY} 09:00:00",
        source_end_time=f"{TODAY} 09:00:20",
    )
    model_continuous_tick = build_activity_display_model(
        report_date=TODAY, today=TODAY, snapshot=snapshot_tick
    )
    rev_continuous_tick, _ = compute_refresh_revision(
        snapshot_tick,
        "running",
        False,
        TODAY,
        report_date=TODAY,
        display_model=model_continuous_tick,
    )
    assert rev_continuous_tick == rev_continuous

    paused_snapshot = dict(snapshot_tick, status=STATUS_PAUSED)
    model_paused = build_activity_display_model(
        report_date=TODAY, today=TODAY, snapshot=paused_snapshot
    )
    rev_paused, _ = compute_refresh_revision(
        paused_snapshot,
        "paused",
        True,
        TODAY,
        report_date=TODAY,
        display_model=model_paused,
    )
    assert rev_paused != rev_continuous
