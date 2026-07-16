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
from worktrace.services import settings_service
from worktrace.services.secure_backup_service import (
    SecureBackupError,
    SecureImportCoordinator,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


def test_pause_timeout_cancels_stale_command():
    control = CollectorControl()

    result = control.request_pause(timeout_seconds=0)

    assert result == {
        "ok": False,
        "pause_pending": False,
        "timed_out": True,
    }
    assert control.take_pause_request() is False


def test_reset_command_is_acknowledged_once():
    control = CollectorControl()
    result_box: dict[str, dict] = {}
    thread = threading.Thread(
        target=lambda: result_box.setdefault(
            "result",
            control.request_reset(timeout_seconds=2),
        ),
        daemon=True,
    )

    thread.start()
    assert control._wake_event.wait(timeout=1)
    assert control.take_reset_request() is True
    control.complete_reset({"ok": True, "reset_pending": False})
    thread.join(timeout=2)

    assert result_box["result"] == {"ok": True, "reset_pending": False}
    assert control.take_reset_request() is False


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


def test_maintenance_coordinator_pauses_and_resets_before_operation(temp_db):
    calls: list[str] = []
    coordinator = SecureImportCoordinator()

    def pause(timeout_seconds=5.0):
        assert coordinator.write_gate_active() is True
        calls.append("pause")
        return {"ok": True, "pause_pending": False}

    def reset(timeout_seconds=5.0):
        assert coordinator.write_gate_active() is True
        calls.append("reset")
        return {"ok": True, "reset_pending": False}

    coordinator.register_collector_pause_handler(pause)
    coordinator.register_collector_reset_handler(reset)

    with coordinator.acquire(reason="test") as guard:
        assert coordinator.write_gate_active() is True
        calls.append("operation")
        guard.mark_succeeded()

    assert calls == ["pause", "reset", "operation"]
    assert coordinator.write_gate_active() is False


def test_maintenance_reset_failure_restores_intent_without_stale_snapshot(temp_db):
    coordinator = SecureImportCoordinator()
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting(
        "current_activity_snapshot",
        '{"persisted_activity_id":77}',
    )
    coordinator.register_collector_pause_handler(
        lambda timeout_seconds=5.0: {"ok": True, "pause_pending": False}
    )
    coordinator.register_collector_reset_handler(
        lambda timeout_seconds=5.0: {"ok": False, "reset_pending": False}
    )

    with pytest.raises(SecureBackupError, match="reset_not_acknowledged"):
        with coordinator.acquire(reason="failure"):
            pytest.fail("operation must not start")

    assert coordinator.write_gate_active() is False
    assert settings_service.get_bool_setting("user_paused", True) is False
    assert settings_service.get_setting("collector_status", "") == "running"
    assert settings_service.get_setting("current_activity_snapshot", "") == ""


def _window() -> ActiveWindow:
    return ActiveWindow("Word", "winword.exe", "Secret.docx")


def test_clipboard_monitor_does_not_start_or_retain_while_disabled():
    monitor = ClipboardMonitor(_window)

    monitor.set_enabled(False)
    assert monitor.drain() == []
    assert monitor._thread is None


def test_clipboard_disable_waits_for_inflight_capture_and_drops_generation(
    monkeypatch,
):
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

    # ``_capture_locked`` uses the same serialization lock as the real loop.
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
