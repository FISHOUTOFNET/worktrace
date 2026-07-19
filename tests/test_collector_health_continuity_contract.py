from tests.support import runtime_state_fixture
import json
import threading

import pytest

from worktrace.collector import collector as collector_mod
from worktrace.collector.collector import run_collector
from worktrace.collector.collector_failure_policy import (
    CollectorFailureCode,
    TransientCollectorError,
)
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import STATUS_ERROR
from worktrace.db import get_connection, now_str
from worktrace.platforms.base import ActiveWindow
from worktrace.services import privacy_gate_service, settings_service

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.contract]


def _transient_adapter_failure() -> TransientCollectorError:
    return TransientCollectorError(
        CollectorFailureCode.ADAPTER_TEMPORARILY_UNAVAILABLE
    )


class _RaisingActiveWindowAdapter:
    def get_active_window(self):
        raise _transient_adapter_failure()

    def get_idle_seconds(self):
        return 0

    def get_clipboard_events(self):
        return []


class _RaisingIdleAdapter:
    def get_active_window(self):
        return ActiveWindow("Word", "word.exe", "Doc")

    def get_idle_seconds(self):
        raise _transient_adapter_failure()

    def get_clipboard_events(self):
        return []


def _assert_no_error_activity_or_boundary_before_stop():
    with get_connection() as conn:
        error_rows = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_log WHERE status = ?",
            (STATUS_ERROR,),
        ).fetchone()["c"]
        boundaries = conn.execute("SELECT COUNT(*) AS c FROM session_boundary").fetchone()["c"]
    assert error_rows == 0
    assert boundaries == 0


def _seed_persisted_open_snapshot() -> int:
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "word.exe", "Doc"),
        at_time=now_str(),
    )
    snapshot = json.loads(
        runtime_state_fixture.get_setting("current_activity_snapshot", "") or "{}"
    )
    activity_id = int(snapshot.get("persisted_activity_id") or 0)
    assert activity_id > 0
    assert snapshot.get("status") == "normal"
    return activity_id


def _assert_same_open_snapshot(snapshot_json: str, activity_id: int) -> None:
    snapshot = json.loads(snapshot_json)
    assert snapshot.get("status") == "normal"
    assert int(snapshot.get("persisted_activity_id") or 0) == activity_id
    with get_connection() as conn:
        row = conn.execute(
            "SELECT end_time, status FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    assert row is not None
    assert row["end_time"] is None
    assert row["status"] == "normal"


@pytest.mark.parametrize("adapter", [_RaisingActiveWindowAdapter(), _RaisingIdleAdapter()])
def test_transient_adapter_failure_only_updates_health_not_activity_continuity(temp_db, monkeypatch, adapter):
    privacy_gate_service.accept_privacy_notice()
    activity_id = _seed_persisted_open_snapshot()
    runtime_state_fixture.set_setting("pending_short_seconds", "17")
    stop_event = threading.Event()
    captured = {}

    def fake_wait(_stop_event, _control, next_poll_deadline):
        captured["pending"] = runtime_state_fixture.get_setting("pending_short_seconds")
        captured["snapshot"] = runtime_state_fixture.get_setting("current_activity_snapshot")
        captured["health"] = settings_service.get_setting("collector_health_state")
        captured["failures"] = settings_service.get_setting("collector_consecutive_failures")
        _assert_no_error_activity_or_boundary_before_stop()
        _assert_same_open_snapshot(captured["snapshot"], activity_id)
        stop_event.set()
        return next_poll_deadline + 1

    monkeypatch.setattr(collector_mod, "_sleep_until_next_poll", fake_wait)

    run_collector(adapter, stop_event)

    assert captured["pending"] == "0"
    assert captured["health"] == "degraded"
    assert captured["failures"] == "1"


def test_privacy_failure_only_updates_health_not_activity_continuity(temp_db, monkeypatch):
    privacy_gate_service.accept_privacy_notice()
    activity_id = _seed_persisted_open_snapshot()
    runtime_state_fixture.set_setting("pending_short_seconds", "19")
    stop_event = threading.Event()
    captured = {}

    class Adapter:
        def get_active_window(self):
            return ActiveWindow("Word", "word.exe", "Doc")

        def get_idle_seconds(self):
            return 0

        def get_clipboard_events(self):
            return []

    monkeypatch.setattr(
        collector_mod.privacy_service,
        "evaluate_exclusion",
        lambda _window: (_ for _ in ()).throw(_transient_adapter_failure()),
    )

    def fake_wait(_stop_event, _control, next_poll_deadline):
        captured["pending"] = runtime_state_fixture.get_setting("pending_short_seconds")
        captured["snapshot"] = runtime_state_fixture.get_setting("current_activity_snapshot")
        captured["phase"] = settings_service.get_setting("collector_last_failure_phase")
        _assert_no_error_activity_or_boundary_before_stop()
        _assert_same_open_snapshot(captured["snapshot"], activity_id)
        stop_event.set()
        return next_poll_deadline + 1

    monkeypatch.setattr(collector_mod, "_sleep_until_next_poll", fake_wait)

    run_collector(Adapter(), stop_event)

    assert captured["pending"] == "0"
    assert captured["phase"] == "privacy"


def test_clipboard_failure_does_not_block_normal_activity_observation(temp_db, monkeypatch):
    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("clipboard_capture_enabled", "true")
    stop_event = threading.Event()
    captured = {}

    class Adapter:
        def get_active_window(self):
            return ActiveWindow("Word", "word.exe", "Doc")

        def get_idle_seconds(self):
            return 0

        def get_clipboard_events(self):
            raise _transient_adapter_failure()

    def fake_wait(_stop_event, _control, next_poll_deadline):
        captured["snapshot"] = runtime_state_fixture.get_setting("current_activity_snapshot")
        captured["last_failure_phase"] = settings_service.get_setting("collector_last_failure_phase")
        _assert_no_error_activity_or_boundary_before_stop()
        stop_event.set()
        return next_poll_deadline + 1

    monkeypatch.setattr(collector_mod, "_sleep_until_next_poll", fake_wait)

    run_collector(Adapter(), stop_event)

    snapshot = json.loads(captured["snapshot"])
    assert snapshot["status"] == "normal"
    assert captured["last_failure_phase"] in ("", "clipboard")


def test_consecutive_transient_failures_reach_failing_without_activity_error(temp_db, monkeypatch):
    privacy_gate_service.accept_privacy_notice()
    stop_event = threading.Event()
    attempts = {"count": 0}
    captured = {}

    def fake_wait(_stop_event, _control, next_poll_deadline):
        attempts["count"] += 1
        if attempts["count"] >= 3:
            captured["health"] = settings_service.get_setting("collector_health_state")
            _assert_no_error_activity_or_boundary_before_stop()
            stop_event.set()
        return next_poll_deadline + 1

    monkeypatch.setattr(collector_mod, "_sleep_until_next_poll", fake_wait)

    run_collector(_RaisingActiveWindowAdapter(), stop_event)

    assert captured["health"] == "failing"
    assert settings_service.get_setting("collector_health_state") == "stopped"
    assert settings_service.get_setting("collector_consecutive_failures") == "3"
    assert settings_service.get_setting("collector_last_failure_phase") == "active_window"
