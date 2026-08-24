from __future__ import annotations

import threading

import pytest

from worktrace.runtime.collector_supervisor import CollectorSupervisor

pytestmark = [pytest.mark.unit, pytest.mark.collector_runtime]


class _CircuitRuntime:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.owns_application_instance = True
        self.running = False
        self.start_calls = 0
        self.recovery_reason = ""

    def collection_liveness_snapshot(self):
        return {
            "state": "recovery_required" if self.recovery_reason else "stopped",
            "live_eligible": False,
        }

    def is_collection_running_for_maintenance(self) -> bool:
        return self.running

    def start_collector(self, *, startup_timeout_seconds: float = 5.0):
        assert startup_timeout_seconds > 0
        self.start_calls += 1
        self.running = True
        return {"ok": True, "started": True, "already_running": False}

    def mark_collector_recovery_required(self, reason: str) -> None:
        self.recovery_reason = reason

    def diagnose_stalled_collector(self) -> None:
        raise AssertionError("stopped collector must not be diagnosed as stalled")


def test_repeated_short_lived_collectors_open_circuit_until_process_recovery():
    runtime = _CircuitRuntime()
    times = iter((0.0, 10.0, 20.0, 30.0))
    supervisor = CollectorSupervisor(
        runtime,
        privacy_allowed_reader=lambda: True,
        user_paused_reader=lambda: False,
        maintenance_in_progress_reader=lambda: False,
        recovery_blocked_reader=lambda: False,
        monotonic_func=lambda: next(times),
        max_restart_attempts=3,
        restart_window_seconds=60,
    )
    supervisor.set_privacy_authorized(True)

    for _ in range(3):
        runtime.running = False
        assert supervisor.check_once() is True
    runtime.running = False

    assert supervisor.check_once() is False
    assert runtime.start_calls == 3
    assert runtime.recovery_reason == "restart_rate_limited"
    assert supervisor.check_once() is False
