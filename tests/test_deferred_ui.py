from __future__ import annotations

import threading

import pytest

from worktrace.desktop.deferred_ui import DeferredUIGate, InitialUIRequest


pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


class _Shell:
    def __init__(self) -> None:
        self.show_calls = 0
        self.exit_calls = 0

    def show_window(self) -> bool:
        self.show_calls += 1
        return True

    def exit_application(self) -> bool:
        self.exit_calls += 1
        return True


def test_concurrent_open_requests_claim_one_initial_ui_bootstrap() -> None:
    gate = DeferredUIGate()
    barrier = threading.Barrier(3)

    def request_open() -> None:
        barrier.wait()
        gate.request_open()

    threads = [threading.Thread(target=request_open) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert gate.wait_for_initial_request(timeout=0.1) is InitialUIRequest.OPEN
    assert gate.wait_for_initial_request(timeout=0.01) is None

    shell = _Shell()
    assert gate.bind_shell(shell) is True
    assert gate.bind_shell(shell) is False
    assert shell.show_calls == 0

    gate.request_open()
    gate.request_open()
    assert shell.show_calls == 2
    assert gate.wait_for_initial_request(timeout=0.01) is None


def test_failed_bootstrap_can_be_requested_again_without_parallel_bootstrap() -> None:
    gate = DeferredUIGate()

    assert gate.request_open() is True
    assert gate.wait_for_initial_request(timeout=0.1) is InitialUIRequest.OPEN
    assert gate.request_open() is False

    gate.mark_initial_open_failed()

    assert gate.request_open() is True
    assert gate.wait_for_initial_request(timeout=0.1) is InitialUIRequest.OPEN


def test_exit_before_ui_creation_wakes_waiter_and_prevents_open() -> None:
    gate = DeferredUIGate()

    assert gate.request_exit() is True
    assert gate.wait_for_initial_request(timeout=0.1) is InitialUIRequest.EXIT
    assert gate.request_open() is False

    shell = _Shell()
    assert gate.bind_shell(shell) is True
    assert shell.exit_calls == 1

    assert gate.request_exit() is False
    assert shell.exit_calls == 1
