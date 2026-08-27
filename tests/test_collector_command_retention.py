from __future__ import annotations

import threading
import time

import pytest

from worktrace.collector.runtime_control import RuntimeCollectorControl

pytestmark = [pytest.mark.unit, pytest.mark.collector_runtime]


def test_runtime_collector_control_bounds_terminal_command_history() -> None:
    control = RuntimeCollectorControl()
    command_ids: list[str] = []

    for _ in range(80):
        result = control.request_pause(timeout_seconds=0.0)
        assert result["command_state"] == "cancelled"
        command_ids.append(str(result["command_id"]))

    with control._lock:
        assert len(control._commands) == 64
    assert control.query_command(command_ids[0]) is None
    newest = control.query_command(command_ids[-1])
    assert newest is not None
    assert newest["command_state"] == "cancelled"


def test_runtime_collector_control_never_prunes_unknown_command() -> None:
    control = RuntimeCollectorControl()
    request_result: dict = {}

    def request_hold() -> None:
        request_result.update(control.request_maintenance_hold(timeout_seconds=0.05))

    thread = threading.Thread(target=request_hold)
    thread.start()
    deadline = time.monotonic() + 1.0
    command_id = None
    while time.monotonic() < deadline and command_id is None:
        command_id = control.take_maintenance_hold_request()
        if command_id is None:
            thread.join(timeout=0.005)
    thread.join(timeout=1.0)

    assert command_id
    assert not thread.is_alive()
    assert request_result["command_state"] == "unknown"

    for _ in range(80):
        result = control.request_pause(timeout_seconds=0.0)
        assert result["command_state"] == "cancelled"

    unknown = control.query_command(command_id)
    assert unknown is not None
    assert unknown["command_state"] == "unknown"
    with control._lock:
        assert len(control._commands) == 65

    assert control.terminalize_unfinished("collector_shutdown") == (command_id,)
    terminal = control.query_command(command_id)
    assert terminal is not None
    assert terminal["command_state"] == "completed"
    assert terminal["terminal_diagnostic"] == "collector_shutdown"
    with control._lock:
        assert len(control._commands) == 64
