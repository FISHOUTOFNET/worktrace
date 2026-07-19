from __future__ import annotations

import threading

import pytest

from worktrace.collector import activity_session_recorder as recorder_module
from worktrace.collector.activity_session_recorder import ActivitySessionRecorder
from worktrace.collector.clock_tracker import ClockTracker
from worktrace.collector.collector import CollectorControl, _sleep_until_next_poll
from worktrace.platforms import windows_clipboard as clipboard_module
from worktrace.platforms.base import ActiveWindow
from worktrace.platforms.windows_clipboard import ClipboardMonitor
from worktrace.security.kdf import KdfError, KdfParams, derive_backup_key
from worktrace.services import (
    database_maintenance_service,
    runtime_activity_state_service,
    settings_service,
)
from worktrace.services.database_maintenance_service import (
    MaintenancePhase,
    RuntimeMaintenanceCoordinator,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


def _ack(kind: str, terminal_state: str) -> dict[str, object]:
    return {
        "ok": True,
        "command_id": f"{kind}-id",
        "command_kind": kind,
        "command_state": "completed",
        "command_state_unknown": False,
        "terminal_state": terminal_state,
    }


class _RuntimeControl:
    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.calls: list[str] = []
        self.quiesce_result = _ack("maintenance_hold", "held")
        self.reset_result = _ack("database_reset", "held")
        self.restore_result = _ack("maintenance_release", "operational")
        self.restored_state = None

    def is_collection_running_for_maintenance(self) -> bool:
        return self.running

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        self.calls.append("hold")
        return dict(self.quiesce_result)

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        self.calls.append("reset")
        return dict(self.reset_result)

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        self.calls.append("release")
        self.restored_state = state
        return dict(self.restore_result)


def _complete_hold(control: CollectorControl) -> None:
    result_box: dict[str, dict] = {}
    request = threading.Thread(
        target=lambda: result_box.setdefault(
            "result",
            control.request_maintenance_hold(timeout_seconds=2),
        ),
        daemon=True,
    )
    request.start()
    assert control._wake_event.wait(timeout=1)
    command_id = control.take_maintenance_hold_request()
    assert command_id is not None
    assert control.complete_maintenance_hold(
        command_id,
        {"ok": True, "hold_pending": False},
    )
    request.join(timeout=2)
    assert result_box["result"]["terminal_state"] == "held"


def test_unclaimed_user_pause_timeout_is_cancelled():
    control = CollectorControl()
    result = control.request_pause(timeout_seconds=0)
    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["command_kind"] == "user_pause"
    assert result["command_state"] == "cancelled"
    assert result["command_state_unknown"] is False
    assert control.take_pause_request() is None


def test_taken_pause_timeout_reports_unknown_and_late_completion_is_queryable():
    control = CollectorControl()
    result_box: dict[str, dict] = {}
    request = threading.Thread(
        target=lambda: result_box.setdefault(
            "result",
            control.request_pause(timeout_seconds=0.05),
        ),
        daemon=True,
    )
    request.start()
    assert control._wake_event.wait(timeout=1)
    command_id = control.take_pause_request()
    assert command_id is not None
    request.join(timeout=1)
    result = result_box["result"]
    assert result["command_id"] == command_id
    assert result["command_kind"] == "user_pause"
    assert result["command_state"] == "unknown"
    assert result["command_state_unknown"] is True
    assert control.complete_pause(
        command_id,
        {"ok": True, "pause_pending": False},
    ) is True
    completed = control.query_command(command_id)
    assert completed is not None
    assert completed["command_state"] == "completed"


def test_reset_requires_held_state_and_is_acknowledged_once():
    control = CollectorControl()
    rejected = control.request_reset(timeout_seconds=0)
    assert rejected["ok"] is False
    assert rejected["error"] == "collector_command_state_conflict"
    _complete_hold(control)

    result_box: dict[str, dict] = {}
    request = threading.Thread(
        target=lambda: result_box.setdefault(
            "result",
            control.request_reset(timeout_seconds=2),
        ),
        daemon=True,
    )
    request.start()
    assert control._wake_event.wait(timeout=1)
    command_id = control.take_reset_request()
    assert command_id is not None
    assert control.complete_reset(
        command_id,
        {"ok": True, "reset_pending": False},
    ) is True
    request.join(timeout=2)
    assert result_box["result"]["command_kind"] == "database_reset"
    assert result_box["result"]["terminal_state"] == "held"
    assert control.take_reset_request() is None


def test_release_returns_collector_to_operational_state():
    control = CollectorControl()
    _complete_hold(control)
    result_box: dict[str, dict] = {}
    request = threading.Thread(
        target=lambda: result_box.setdefault(
            "result",
            control.request_maintenance_release(timeout_seconds=2),
        ),
        daemon=True,
    )
    request.start()
    assert control._wake_event.wait(timeout=1)
    command_id = control.take_maintenance_release_request()
    assert command_id is not None
    assert control.complete_maintenance_release(
        command_id,
        {"ok": True, "release_pending": False},
    )
    request.join(timeout=2)
    assert result_box["result"]["command_kind"] == "maintenance_release"
    assert result_box["result"]["terminal_state"] == "operational"


def test_long_poll_gap_rebases_instead_of_replaying_ticks():
    next_deadline = _sleep_until_next_poll(
        threading.Event(),
        None,
        1.0,
        monotonic_func=lambda: 28_800.0,
        wait_func=lambda *_args: pytest.fail("must not wait after long gap"),
    )
    assert next_deadline == pytest.approx(28_801.0)


def test_clock_tracker_detects_collector_stall():
    tracker = ClockTracker()
    assert tracker.observe(
        "2026-07-15 09:00:00",
        100.0,
        clock_jump_threshold_seconds=300,
        stall_threshold_seconds=180,
    ) is None
    event = tracker.observe(
        "2026-07-15 09:10:00",
        700.0,
        clock_jump_threshold_seconds=300,
        stall_threshold_seconds=180,
    )
    assert event is not None
    assert event.reason == "collector_stall"
    assert event.safe_end_time == "2026-07-15 09:00:00"


def test_clock_tracker_detects_backward_wall_clock_jump():
    tracker = ClockTracker()
    tracker.observe(
        "2026-07-15 10:00:00",
        100.0,
        clock_jump_threshold_seconds=300,
        stall_threshold_seconds=180,
    )
    event = tracker.observe(
        "2026-07-15 09:00:00",
        101.0,
        clock_jump_threshold_seconds=300,
        stall_threshold_seconds=180,
    )
    assert event is not None
    assert event.reason == "clock_jump_backward"
    assert event.safe_end_time == "2026-07-15 09:00:00"


def test_clock_tracker_detects_forward_wall_clock_jump():
    tracker = ClockTracker()
    tracker.observe(
        "2026-07-15 10:00:00",
        100.0,
        clock_jump_threshold_seconds=300,
        stall_threshold_seconds=180,
    )
    event = tracker.observe(
        "2026-07-15 12:00:00",
        101.0,
        clock_jump_threshold_seconds=300,
        stall_threshold_seconds=180,
    )
    assert event is not None
    assert event.reason == "clock_jump_forward"
    assert event.safe_end_time == "2026-07-15 10:00:01"


def test_recorder_generation_reset_forgets_old_activity_id(monkeypatch):
    cleared: list[str] = []

    class Publisher:
        def clear(self, reason: str) -> None:
            cleared.append(reason)

    monkeypatch.setattr(
        recorder_module,
        "clear_runtime_activity_state",
        lambda reason: cleared.append(reason),
    )
    recorder = ActivitySessionRecorder(snapshot_publisher=Publisher())
    recorder.current_payload = {"status": "normal"}
    recorder.current_signature = ("normal", "kind", "subtype", "identity")
    recorder.current_start_time = "2026-07-15 09:00:00"
    recorder.current_last_seen_time = "2026-07-15 09:01:00"
    recorder.persisted_activity_id = 77
    recorder.clear_runtime_state("database_generation_changed")
    assert recorder.current_payload is None
    assert recorder.current_signature is None
    assert recorder.current_start_time is None
    assert recorder.current_last_seen_time is None
    assert recorder.persisted_activity_id is None
    assert "database_generation_changed" in cleared


def test_snapshot_holds_and_releases_without_replacement_reset(temp_db, monkeypatch):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl()
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    with coordinator.consistent_snapshot("test"):
        assert coordinator.phase is MaintenancePhase.EXCLUSIVE
        control.calls.append("operation")
    assert control.calls == ["hold", "operation", "release"]
    assert control.restored_state is not None
    assert control.restored_state.collector_running is True
    assert control.restored_state.user_paused is False
    assert coordinator.phase is MaintenancePhase.IDLE


def test_replacement_resets_after_exclusive_and_before_release(temp_db, monkeypatch):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl()
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    with coordinator.database_replacement("replacement"):
        assert coordinator.phase is MaintenancePhase.EXCLUSIVE
        control.calls.append("operation")
    assert control.calls == ["hold", "operation", "reset", "release"]


def test_replacement_reset_failure_fails_closed_and_clears_snapshot(temp_db, monkeypatch):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl()
    control.reset_result = {
        "ok": False,
        "command_id": "reset-id",
        "command_kind": "database_reset",
        "command_state": "cancelled",
        "command_state_unknown": False,
        "terminal_state": "held",
    }
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    runtime_activity_state_service.publish_runtime_activity_snapshot(
        {"persisted_activity_id": 77},
        "maintenance_test",
    )
    with pytest.raises(RuntimeError, match="collector_database_reset_not_acknowledged"):
        with coordinator.database_replacement("failure"):
            pass
    assert coordinator.active() is False
    assert settings_service.get_bool_setting("user_paused", False) is True
    assert settings_service.get_setting("collector_status", "") == "paused"
    assert runtime_activity_state_service.sample_runtime_activity_state().snapshot is None


def test_unknown_hold_command_state_remains_fail_closed(temp_db, monkeypatch):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl()
    control.quiesce_result = {
        "ok": False,
        "command_id": "hold-id",
        "command_kind": "maintenance_hold",
        "command_state": "unknown",
        "command_state_unknown": True,
        "terminal_state": "sealing",
    }
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    with pytest.raises(RuntimeError, match="collector_maintenance_hold_not_acknowledged"):
        with coordinator.consistent_snapshot("unknown"):
            pytest.fail("operation must not start")
    assert coordinator.active() is False
    assert settings_service.get_bool_setting("user_paused", False) is True
    assert settings_service.get_setting("collector_status", "") == "paused"


def test_user_pause_and_privacy_gate_are_preserved(temp_db, monkeypatch):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl()
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "true")
    settings_service.set_setting("collector_status", "paused")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: False,
    )
    with coordinator.consistent_snapshot("privacy_gate"):
        pass
    assert control.restored_state is not None
    assert control.restored_state.privacy_notice_accepted is False
    assert control.restored_state.user_paused is True
    assert settings_service.get_bool_setting("user_paused", False) is True
    assert settings_service.get_setting("collector_status", "") == "paused"


def _window() -> ActiveWindow:
    return ActiveWindow("Word", "winword.exe", "Secret.docx")


def test_clipboard_monitor_does_not_start_or_retain_while_disabled():
    monitor = ClipboardMonitor(_window)
    monitor.set_enabled(False)
    assert monitor.drain() == []
    assert monitor._thread is None


def test_clipboard_disable_waits_for_inflight_capture_and_drops_generation(monkeypatch):
    read_started = threading.Event()
    allow_read = threading.Event()

    def read_text():
        read_started.set()
        assert allow_read.wait(timeout=2)
        return "sensitive"

    monkeypatch.setattr(
        clipboard_module,
        "read_clipboard_unicode_text",
        read_text,
    )
    monitor = ClipboardMonitor(_window)
    monitor.set_enabled(True)
    generation = monitor._generation

    def serialized_capture():
        with monitor._lifecycle_lock:
            monitor._capture_locked(7, generation)

    capture = threading.Thread(target=serialized_capture, daemon=True)
    capture.start()
    assert read_started.wait(timeout=1)
    disabled = threading.Event()
    disable_thread = threading.Thread(
        target=lambda: (monitor.set_enabled(False), disabled.set()),
        daemon=True,
    )
    disable_thread.start()
    assert disabled.wait(timeout=0.05) is False
    allow_read.set()
    capture.join(timeout=2)
    disable_thread.join(timeout=2)
    assert disabled.is_set()
    assert monitor.drain() == []
    monitor.shutdown()


def test_kdf_rejects_excessive_resource_parameters():
    with pytest.raises(KdfError, match="resource"):
        derive_backup_key(
            "passphrase",
            b"0" * 16,
            KdfParams(n=2**19, r=8, p=1),
        )
