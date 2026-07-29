from __future__ import annotations

import threading

import pytest

from worktrace.collector.single_instance import ApplicationInstanceCoordinator

pytestmark = [pytest.mark.collector_runtime, pytest.mark.contract]


class FakeActivationKernel:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.signal_calls = 0

    def create_activation_event(self, _name: str):
        return self.event

    def signal_activation_event(self, _name: str) -> bool:
        self.signal_calls += 1
        self.event.set()
        return True

    def wait_for_activation(self, event, timeout_seconds: float) -> bool:
        signaled = event.wait(timeout_seconds)
        if signaled:
            event.clear()
        return signaled

    def wake_activation_waiter(self, event) -> None:
        event.set()

    def close_activation_event(self, _event) -> None:
        return None


def test_second_instance_sends_activation_signal() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)

    assert coordinator.signal_existing_instance(retries=1) is True
    assert kernel.signal_calls == 1


def test_primary_instance_receives_signal_and_requests_show() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)
    shown = threading.Event()
    coordinator.start_activation_listener(shown.set)
    try:
        assert coordinator.signal_existing_instance(retries=1) is True
        assert shown.wait(1.0)
    finally:
        coordinator.stop_activation_listener()
