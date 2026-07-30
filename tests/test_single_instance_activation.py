from __future__ import annotations

import inspect
import threading

import pytest

from worktrace.collector.single_instance import ApplicationInstanceCoordinator

pytestmark = [pytest.mark.collector_runtime, pytest.mark.contract]


class FakeActivationKernel:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.create_calls = 0
        self.prepared_signal_calls = 0
        self.named_signal_calls = 0
        self.close_calls = 0
        self.activation_consumed = threading.Event()

    def create_activation_event(self, _name: str):
        self.create_calls += 1
        return self.event

    def signal_prepared_activation(self, event) -> bool:
        assert event is self.event
        self.prepared_signal_calls += 1
        event.set()
        return True

    def signal_activation_event(self, _name: str) -> bool:
        self.named_signal_calls += 1
        self.event.set()
        return True

    def wait_for_activation(self, event, timeout_seconds: float) -> bool:
        signaled = event.wait(timeout_seconds)
        if signaled:
            event.clear()
            self.activation_consumed.set()
        return signaled

    def wake_activation_waiter(self, event) -> None:
        event.set()

    def close_activation_event(self, event) -> None:
        assert event is self.event
        self.close_calls += 1


def test_activation_event_is_prepared_idempotently_before_listener() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)

    coordinator.prepare_activation_event()
    coordinator.prepare_activation_event()

    assert kernel.create_calls == 1
    assert kernel.close_calls == 0
    coordinator.stop_activation_listener()
    assert kernel.close_calls == 1


def test_signal_before_listener_start_is_retained_by_prepared_event() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)
    shown = threading.Event()

    coordinator.prepare_activation_event()
    assert coordinator.signal_existing_instance() is True
    assert kernel.prepared_signal_calls == 1
    assert kernel.named_signal_calls == 0

    coordinator.start_activation_listener()
    coordinator.bind_activation_handler(shown.set)
    try:
        assert shown.wait(1.0)
    finally:
        coordinator.stop_activation_listener()


def test_signal_before_handler_binding_becomes_one_pending_activation() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)
    shown = threading.Event()
    calls = 0

    def show() -> None:
        nonlocal calls
        calls += 1
        shown.set()

    coordinator.prepare_activation_event()
    coordinator.start_activation_listener()
    assert coordinator.signal_existing_instance() is True
    assert kernel.activation_consumed.wait(1.0)

    coordinator.bind_activation_handler(show)
    coordinator.bind_activation_handler(show)
    try:
        assert shown.wait(1.0)
        assert calls == 1
    finally:
        coordinator.stop_activation_listener()


def test_activation_callback_runs_outside_coordinator_lock() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)
    callback_completed = threading.Event()

    def callback() -> None:
        rebound = threading.Event()
        thread = threading.Thread(
            target=lambda: (
                coordinator.bind_activation_handler(callback),
                rebound.set(),
            )
        )
        thread.start()
        assert rebound.wait(1.0), "callback ran while coordinator lock was held"
        thread.join(timeout=1.0)
        callback_completed.set()

    coordinator.prepare_activation_event()
    coordinator.start_activation_listener()
    coordinator.bind_activation_handler(callback)
    try:
        assert coordinator.signal_existing_instance() is True
        assert callback_completed.wait(1.0)
    finally:
        coordinator.stop_activation_listener()


def test_prepare_start_bind_and_stop_are_idempotent() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)
    callback = lambda: None

    coordinator.prepare_activation_event()
    coordinator.prepare_activation_event()
    coordinator.start_activation_listener()
    coordinator.start_activation_listener()
    coordinator.bind_activation_handler(callback)
    coordinator.bind_activation_handler(callback)
    coordinator.stop_activation_listener()
    coordinator.stop_activation_listener()

    assert kernel.create_calls == 1
    assert kernel.close_calls == 1


def test_stop_prevents_later_activation_callback() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)
    callback_calls = 0

    def callback() -> None:
        nonlocal callback_calls
        callback_calls += 1

    coordinator.prepare_activation_event()
    coordinator.start_activation_listener()
    coordinator.bind_activation_handler(callback)
    coordinator.stop_activation_listener()

    kernel.event.set()
    assert callback_calls == 0
    assert kernel.close_calls == 1


def test_normal_signal_path_does_not_use_named_open_or_retry() -> None:
    kernel = FakeActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)
    coordinator.prepare_activation_event()

    try:
        assert tuple(
            inspect.signature(coordinator.signal_existing_instance).parameters
        ) == ()
        assert coordinator.signal_existing_instance() is True
        assert kernel.prepared_signal_calls == 1
        assert kernel.named_signal_calls == 0
    finally:
        coordinator.stop_activation_listener()
