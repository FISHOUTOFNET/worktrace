from __future__ import annotations

import threading

import pytest

from worktrace.collector import activity_session_recorder as recorder_module
from worktrace.collector.activity_session_recorder import ActivitySessionRecorder
from worktrace.collector.clock_tracker import ClockTracker
from worktrace.collector.collector import CollectorControl, _sleep_until_next_poll
from worktrace.platforms.hardened_windows_adapter import _ClipboardMonitor
from worktrace.security.kdf import KdfError, KdfParams, derive_backup_key
from worktrace.services.secure_backup_service import SecureImportCoordinator

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
    coordinator.register_collector_pause_handler(
        lambda timeout_seconds=5.0: (
            calls.append("pause")
            or {"ok": True, "pause_pending": False}
        )
    )
    coordinator.register_collector_reset_handler(
        lambda timeout_seconds=5.0: (
            calls.append("reset")
            or {"ok": True, "reset_pending": False}
        )
    )

    with coordinator.acquire(reason="test") as guard:
        calls.append("operation")
        guard.mark_succeeded()

    assert calls == ["pause", "reset", "operation"]


def test_clipboard_monitor_does_not_start_or_retain_while_disabled():
    monitor = _ClipboardMonitor()

    monitor.set_enabled(False)
    assert monitor.drain() == []
    assert monitor._thread is None


def test_kdf_rejects_excessive_resource_parameters():
    with pytest.raises(KdfError, match="resource"):
        derive_backup_key(
            "passphrase",
            b"0" * 16,
            KdfParams(n=2**19, r=8, p=1),
        )
