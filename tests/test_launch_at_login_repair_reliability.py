from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import worktrace.platforms.windows_startup as windows_startup
from worktrace.platforms.startup import (
    LaunchAtLoginRepairError,
    LaunchAtLoginRepairOutcome,
)
from worktrace.platforms.windows_startup import (
    TASK_NAME,
    StartupTaskSpec,
    WindowsLaunchAtLoginRepair,
    WindowsStartupRegistration,
)
from worktrace.runtime.app_runtime import AppRuntime, WorkerLaunchKind
from worktrace.runtime.launch_at_login_repair import (
    run_launch_at_login_repair_worker,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]


class _Health:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.successes = 0

    def failed(self, code: str) -> None:
        self.failures.append(code)

    def succeeded(self) -> None:
        self.successes += 1

    def maintenance_paused(self, _paused: bool) -> None: pass


class _SequenceRepair:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.calls = 0

    def repair_once(self):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _run_until_calls(repair, expected: int, **kwargs):
    stop = threading.Event()
    health = _Health()
    thread = threading.Thread(
        target=run_launch_at_login_repair_worker,
        args=(stop, repair),
        kwargs={"health": health, **kwargs},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 2.0
    while repair.calls < expected and time.monotonic() < deadline:
        time.sleep(0.005)
    assert repair.calls == expected
    return stop, health, thread


def test_repair_worker_recovers_after_transient_failure() -> None:
    repair = _SequenceRepair(
        [
            LaunchAtLoginRepairError(
                "launch_at_login_task_scheduler_transient",
                retryable=True,
                native_codes=(-2147023174,),
            ),
            LaunchAtLoginRepairOutcome.REPAIRED,
        ]
    )
    stop, health, thread = _run_until_calls(
        repair,
        2,
        initial_delay_seconds=0.0,
        max_delay_seconds=0.0,
    )
    deadline = time.monotonic() + 1.0
    while health.successes < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    stop.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert health.failures == ["launch_at_login_task_scheduler_transient"]
    assert health.successes == 1


def test_repair_worker_stops_after_retry_limit() -> None:
    failures = [
        LaunchAtLoginRepairError(
            "launch_at_login_task_scheduler_transient",
            retryable=True,
        )
        for _ in range(3)
    ]
    repair = _SequenceRepair(failures)
    stop, health, thread = _run_until_calls(
        repair,
        3,
        max_attempts=3,
        initial_delay_seconds=0.0,
        max_delay_seconds=0.0,
    )
    time.sleep(0.03)
    assert repair.calls == 3
    stop.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(health.failures) == 3
    assert health.successes == 0


def test_repair_worker_does_not_retry_permanent_failure() -> None:
    repair = _SequenceRepair(
        [
            LaunchAtLoginRepairError(
                "launch_at_login_access_denied",
                retryable=False,
                native_codes=(-2147024891,),
            )
        ]
    )
    stop, health, thread = _run_until_calls(repair, 1)
    time.sleep(0.03)
    assert repair.calls == 1
    stop.set()
    thread.join(timeout=1.0)

    assert health.failures == ["launch_at_login_access_denied"]
    assert health.successes == 0


def test_repair_backoff_is_shutdown_cancellable() -> None:
    repair = _SequenceRepair(
        [
            LaunchAtLoginRepairError(
                "launch_at_login_task_scheduler_transient",
                retryable=True,
            )
        ]
    )
    stop, _health, thread = _run_until_calls(
        repair,
        1,
        initial_delay_seconds=60.0,
        max_delay_seconds=60.0,
    )
    started = time.monotonic()
    stop.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert time.monotonic() - started < 1.0
    assert repair.calls == 1


class _NestedComError(Exception):
    def __init__(self, inner_hresult: int) -> None:
        self.hresult = -2147352567
        super().__init__(
            self.hresult,
            "Exception occurred.",
            (0, None, None, None, 0, inner_hresult),
            None,
        )


class _FailingRegistration:
    supported = True

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def repair_if_needed(self):
        raise self.exc


def test_windows_repair_classifies_nested_transient_hresult(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None),
    )
    repair = WindowsLaunchAtLoginRepair(
        _FailingRegistration(_NestedComError(-2147023174))
    )

    with pytest.raises(LaunchAtLoginRepairError) as caught:
        repair.repair_once()

    assert caught.value.retryable is True
    assert caught.value.code == "launch_at_login_task_scheduler_transient"
    assert -2147023174 in caught.value.native_codes


class _Registry:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def read_run_value(self, _name: str) -> str | None:
        return self.value

    def delete_run_value(self, _name: str) -> None:
        self.value = None


class _BlockingScheduler:
    def __init__(self) -> None:
        self.task_exists = True
        self.configured = False
        self.exists_entered = threading.Event()
        self.release_exists = threading.Event()
        self.deleted = threading.Event()

    def exists(self, _name: str) -> bool:
        self.exists_entered.set()
        assert self.release_exists.wait(1.0)
        return self.task_exists

    def is_configured(self, _name: str, _spec: StartupTaskSpec) -> bool:
        return self.task_exists and self.configured

    def register(self, _name: str, _spec: StartupTaskSpec) -> None:
        self.task_exists = True
        self.configured = True

    def delete(self, _name: str) -> None:
        self.task_exists = False
        self.configured = False
        self.deleted.set()


def test_repair_and_user_disable_are_serialized(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    scheduler = _BlockingScheduler()
    registration = WindowsStartupRegistration(
        executable_path=tmp_path / "Trace.exe",
        registry=_Registry(),
        scheduler=scheduler,
    )
    repair_done = threading.Event()
    disable_done = threading.Event()

    def repair() -> None:
        registration.repair_if_needed()
        repair_done.set()

    def disable() -> None:
        registration.disable()
        disable_done.set()

    repair_thread = threading.Thread(target=repair)
    repair_thread.start()
    assert scheduler.exists_entered.wait(1.0)
    disable_thread = threading.Thread(target=disable)
    disable_thread.start()
    time.sleep(0.03)
    assert scheduler.deleted.is_set() is False

    scheduler.release_exists.set()
    repair_thread.join(timeout=1.0)
    disable_thread.join(timeout=1.0)

    assert repair_done.is_set()
    assert disable_done.is_set()
    assert scheduler.task_exists is False
    assert scheduler.configured is False


class _Adapter:
    def run_clipboard_capture(self, *_args, **_kwargs) -> None: pass

    def shutdown(self) -> None: pass


def test_launch_repair_worker_uses_initialize_launch_kind_and_is_not_runtime_relevant() -> None:
    repair = _SequenceRepair([LaunchAtLoginRepairOutcome.DISABLED])
    paths = SimpleNamespace(db_path="unused", log_path="unused")
    runtime = AppRuntime(
        paths,
        adapter=_Adapter(),
        launch_at_login_repair=repair,
    )
    spec = runtime._worker_specs["launch_at_login_repair"]

    assert spec.launch_kind is WorkerLaunchKind.INITIALIZE
    assert spec.runtime_relevant is False
    assert spec.thread_name == "WorkTraceLaunchAtLoginRepair"
