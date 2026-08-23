from __future__ import annotations

import threading

import pytest

from worktrace.runtime.collector_supervisor import CollectorSupervisor

pytestmark = [pytest.mark.unit, pytest.mark.collector_runtime]


class _Runtime:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.owns_application_instance = True
        self.running = False
        self.start_calls = 0
        self.start_result = {"ok": True, "started": True, "already_running": False}

    def is_collection_running_for_maintenance(self) -> bool:
        return self.running

    def start_collector(self, *, startup_timeout_seconds: float = 5.0):
        assert startup_timeout_seconds > 0
        self.start_calls += 1
        if self.start_result.get("ok"):
            self.running = True
        return dict(self.start_result)


def _supervisor(runtime, *, now=lambda: 0.0, paused=lambda: False, maintenance=lambda: False):
    supervisor = CollectorSupervisor(
        runtime,
        privacy_allowed_reader=lambda: True,
        user_paused_reader=paused,
        maintenance_in_progress_reader=maintenance,
        recovery_blocked_reader=lambda: False,
        monotonic_func=now,
        max_restart_attempts=3,
        restart_window_seconds=60,
    )
    supervisor.set_privacy_authorized(True)
    return supervisor


def test_dead_authorized_collector_is_restarted_without_ui_request():
    runtime = _Runtime()
    supervisor = _supervisor(runtime)

    assert supervisor.check_once() is True
    assert runtime.start_calls == 1
    assert runtime.running is True
    assert supervisor.check_once() is False
    assert runtime.start_calls == 1


def test_user_pause_and_maintenance_block_automatic_restart():
    paused_runtime = _Runtime()
    paused = _supervisor(paused_runtime, paused=lambda: True)
    assert paused.check_once() is False
    assert paused_runtime.start_calls == 0

    maintenance_runtime = _Runtime()
    maintenance = _supervisor(maintenance_runtime, maintenance=lambda: True)
    assert maintenance.check_once() is False
    assert maintenance_runtime.start_calls == 0


def test_privacy_and_runtime_shutdown_fail_closed():
    runtime = _Runtime()
    supervisor = _supervisor(runtime)
    supervisor.set_privacy_authorized(False)
    assert supervisor.check_once() is False
    assert runtime.start_calls == 0

    supervisor.set_privacy_authorized(True)
    runtime.stop_event.set()
    assert supervisor.check_once() is False
    assert runtime.start_calls == 0


def test_repeated_crashes_are_rate_limited_then_recover_after_window():
    runtime = _Runtime()
    times = iter((0.0, 10.0, 20.0, 30.0, 61.0))
    supervisor = _supervisor(runtime, now=lambda: next(times))

    for _ in range(3):
        runtime.running = False
        assert supervisor.check_once() is True
    assert runtime.start_calls == 3

    runtime.running = False
    assert supervisor.check_once() is False
    assert runtime.start_calls == 3

    runtime.running = False
    assert supervisor.check_once() is True
    assert runtime.start_calls == 4
