from __future__ import annotations

import threading

import pytest

from worktrace.desktop.update_shutdown import ApplicationUpdateShutdownCoordinator

pytestmark = [pytest.mark.packaging, pytest.mark.contract]


class FakeUpdateShutdownKernel:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.create_calls = 0
        self.signal_calls = 0
        self.close_calls = 0
        self.consumed = threading.Event()

    def create_event(self, _name: str):
        self.create_calls += 1
        return self.event

    def signal_event(self, _name: str) -> bool:
        self.signal_calls += 1
        self.event.set()
        return True

    def wait_for_signal(self, event, timeout_seconds: float) -> bool:
        signaled = event.wait(timeout_seconds)
        if signaled:
            event.clear()
            self.consumed.set()
        return signaled

    def wake_waiter(self, event) -> None:
        event.set()

    def close_event(self, event) -> None:
        assert event is self.event
        self.close_calls += 1


def test_signal_before_listener_and_binding_is_delivered_once() -> None:
    kernel = FakeUpdateShutdownKernel()
    coordinator = ApplicationUpdateShutdownCoordinator(kernel=kernel)
    called = threading.Event()
    count = 0

    def shutdown() -> None:
        nonlocal count
        count += 1
        called.set()

    coordinator.prepare()
    assert coordinator.signal_running_instance() is True
    coordinator.start_listener()
    assert kernel.consumed.wait(1.0)
    coordinator.bind_shutdown_handler(shutdown)
    try:
        assert called.wait(1.0)
        assert count == 1
    finally:
        coordinator.close()


def test_stop_listener_retains_lifetime_event_until_close() -> None:
    kernel = FakeUpdateShutdownKernel()
    coordinator = ApplicationUpdateShutdownCoordinator(kernel=kernel)

    coordinator.prepare()
    coordinator.start_listener()
    coordinator.stop_listener()

    assert kernel.close_calls == 0
    coordinator.close()
    assert kernel.close_calls == 1


def test_shutdown_callback_runs_outside_coordinator_lock() -> None:
    kernel = FakeUpdateShutdownKernel()
    coordinator = ApplicationUpdateShutdownCoordinator(kernel=kernel)
    completed = threading.Event()

    def shutdown() -> None:
        rebound = threading.Event()
        thread = threading.Thread(
            target=lambda: (
                coordinator.bind_shutdown_handler(shutdown),
                rebound.set(),
            )
        )
        thread.start()
        assert rebound.wait(1.0)
        thread.join(timeout=1.0)
        completed.set()

    coordinator.prepare()
    coordinator.start_listener()
    coordinator.bind_shutdown_handler(shutdown)
    try:
        assert coordinator.signal_running_instance() is True
        assert completed.wait(1.0)
    finally:
        coordinator.close()


def test_prepare_start_stop_and_close_are_idempotent() -> None:
    kernel = FakeUpdateShutdownKernel()
    coordinator = ApplicationUpdateShutdownCoordinator(kernel=kernel)

    coordinator.prepare()
    coordinator.prepare()
    coordinator.start_listener()
    coordinator.start_listener()
    coordinator.stop_listener()
    coordinator.stop_listener()
    coordinator.close()
    coordinator.close()

    assert kernel.create_calls == 1
    assert kernel.close_calls == 1
