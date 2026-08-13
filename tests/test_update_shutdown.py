from __future__ import annotations

import threading

import pytest

import worktrace.desktop.update_shutdown as update_shutdown_module
from worktrace.desktop.update_shutdown import ApplicationUpdateShutdownCoordinator

pytestmark = [
    pytest.mark.packaging,
    pytest.mark.contract,
    pytest.mark.collector_runtime,
]


class FakeUpdateShutdownKernel:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.create_calls = 0
        self.signal_calls = 0
        self.close_calls = 0
        self.consumed = threading.Event()
        self.running = False
        self.close_on_signal = False

    def create_event(self, _name: str):
        self.create_calls += 1
        self.running = True
        return self.event

    def event_exists(self, _name: str) -> bool:
        return self.running

    def signal_event(self, _name: str) -> bool:
        self.signal_calls += 1
        if not self.running:
            return False
        self.event.set()
        if self.close_on_signal:
            self.running = False
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
        self.running = False
        self.close_calls += 1


class FakeProcessProbe:
    def __init__(self, *, pids: set[int] | None = None, alive_checks=None) -> None:
        self.pids = set(pids or set())
        self.alive_checks = list(alive_checks or [])
        self.snapshots = 0
        self.checked: list[set[int]] = []

    def snapshot_other_same_executable_pids(self) -> set[int]:
        self.snapshots += 1
        return set(self.pids)

    def any_alive(self, pids: set[int]) -> bool:
        self.checked.append(set(pids))
        if self.alive_checks:
            return bool(self.alive_checks.pop(0))
        return False


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
    assert kernel.running is True
    coordinator.close()
    assert kernel.close_calls == 1
    assert kernel.running is False


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


def test_maintenance_client_succeeds_when_no_compatible_instance_exists() -> None:
    kernel = FakeUpdateShutdownKernel()
    probe = FakeProcessProbe()
    coordinator = ApplicationUpdateShutdownCoordinator(
        kernel=kernel,
        process_probe=probe,
    )

    assert coordinator.request_running_instance_shutdown(timeout_seconds=0.0) is True
    assert kernel.signal_calls == 0
    assert probe.snapshots == 1


def test_maintenance_client_signals_and_waits_for_lifetime_event_to_close() -> None:
    kernel = FakeUpdateShutdownKernel()
    kernel.running = True
    kernel.close_on_signal = True
    probe = FakeProcessProbe()
    coordinator = ApplicationUpdateShutdownCoordinator(
        kernel=kernel,
        process_probe=probe,
    )

    assert coordinator.request_running_instance_shutdown(timeout_seconds=0.0) is True
    assert kernel.signal_calls == 1
    assert kernel.running is False


def test_maintenance_client_waits_for_onefile_parent_after_event_closes(
    monkeypatch,
) -> None:
    kernel = FakeUpdateShutdownKernel()
    kernel.running = True
    kernel.close_on_signal = True
    probe = FakeProcessProbe(pids={101, 102}, alive_checks=[True, False])
    coordinator = ApplicationUpdateShutdownCoordinator(
        kernel=kernel,
        process_probe=probe,
    )
    monotonic_values = iter([0.0, 0.0, 0.01])
    monkeypatch.setattr(
        update_shutdown_module.time,
        "monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(update_shutdown_module.time, "sleep", lambda _value: None)

    assert coordinator.request_running_instance_shutdown(timeout_seconds=1.0) is True
    assert kernel.signal_calls == 1
    assert probe.checked == [{101, 102}, {101, 102}]


def test_maintenance_client_fails_when_same_executable_remains_without_event() -> None:
    kernel = FakeUpdateShutdownKernel()
    probe = FakeProcessProbe(pids={101}, alive_checks=[True])
    coordinator = ApplicationUpdateShutdownCoordinator(
        kernel=kernel,
        process_probe=probe,
    )

    assert coordinator.request_running_instance_shutdown(timeout_seconds=0.0) is False
    assert kernel.signal_calls == 0


def test_maintenance_client_fails_closed_when_running_instance_does_not_exit() -> None:
    kernel = FakeUpdateShutdownKernel()
    kernel.running = True
    coordinator = ApplicationUpdateShutdownCoordinator(kernel=kernel)

    assert coordinator.request_running_instance_shutdown(timeout_seconds=0.0) is False
    assert kernel.signal_calls == 1
    assert kernel.running is True
