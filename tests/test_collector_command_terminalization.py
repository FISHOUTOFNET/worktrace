from __future__ import annotations

import threading
import time

from worktrace.collector.collector import CollectorCommandKind
from worktrace.collector.runtime_control import RuntimeCollectorControl


def _request_in_thread(control: RuntimeCollectorControl, result: dict) -> threading.Thread:
    def request() -> None:
        result.update(control.request_maintenance_hold(timeout_seconds=2.0))

    thread = threading.Thread(target=request)
    thread.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with control._lock:
            if CollectorCommandKind.MAINTENANCE_HOLD in control._pending_ids:
                break
        time.sleep(0.005)
    return thread


def test_shutdown_cancels_pending_command_with_terminal_diagnostic() -> None:
    control = RuntimeCollectorControl()
    result: dict = {}
    thread = _request_in_thread(control, result)

    terminalized = control.terminalize_unfinished("collector_shutdown")
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(terminalized) == 1
    assert result["ok"] is False
    assert result["command_kind"] == "maintenance_hold"
    assert result["command_state"] == "cancelled"
    assert result["command_state_unknown"] is False
    assert result["terminal_diagnostic"] == "collector_shutdown"


def test_fatal_exit_terminalizes_taken_command_and_rejects_late_completion() -> None:
    control = RuntimeCollectorControl()
    result: dict = {}
    thread = _request_in_thread(control, result)
    command_id = control.take_maintenance_hold_request()

    assert command_id
    terminalized = control.terminalize_unfinished("collector_fatal_exit")
    thread.join(timeout=1.0)

    assert terminalized == (command_id,)
    assert result["ok"] is False
    assert result["command_id"] == command_id
    assert result["command_state"] == "completed"
    assert result["command_state_unknown"] is False
    assert result["terminal_diagnostic"] == "collector_fatal_exit"
    assert control.query_command(command_id) == result
    assert control.complete_maintenance_hold(command_id, {"ok": True}) is False


def test_timeout_unknown_can_be_terminalized_after_requester_returns() -> None:
    control = RuntimeCollectorControl()
    result: dict = {}

    def request() -> None:
        result.update(control.request_maintenance_hold(timeout_seconds=0.05))

    thread = threading.Thread(target=request)
    thread.start()
    deadline = time.monotonic() + 1.0
    command_id = None
    while time.monotonic() < deadline and command_id is None:
        command_id = control.take_maintenance_hold_request()
        if command_id is None:
            time.sleep(0.005)
    thread.join(timeout=1.0)

    assert command_id
    assert result["command_state"] == "unknown"
    assert result["command_state_unknown"] is True

    assert control.terminalize_unfinished("collector_shutdown") == (command_id,)
    terminal = control.query_command(command_id)
    assert terminal is not None
    assert terminal["command_state"] == "completed"
    assert terminal["command_state_unknown"] is False
    assert terminal["terminal_diagnostic"] == "collector_shutdown"
