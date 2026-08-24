from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import AppRuntime, RuntimePhase, WorkerSpec


pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def _owned_runtime() -> AppRuntime:
    runtime = AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=FakeAdapter(),
    )
    runtime.owns_application_instance = True
    runtime._initialized = True
    return runtime


def _join_workers(runtime: AppRuntime) -> None:
    runtime.request_shutdown()
    for handle in list(runtime._worker_handles.values()):
        if handle.thread is not None:
            handle.thread.join(timeout=1.0)


def test_worker_startup_ready_is_not_coupled_to_first_iteration_success(temp_db) -> None:
    runtime = _owned_runtime()
    iteration_entered = threading.Event()

    def transiently_busy(stop_event, *, health):
        health.failed("database_busy")
        iteration_entered.set()
        stop_event.wait(1.0)

    runtime._worker_specs = {
        "busy": WorkerSpec(
            name="busy",
            thread_name="WorkTraceBusyWorker",
            target=transiently_busy,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.1,
        )
    }

    try:
        report = runtime.start_background_workers()

        assert report.ready is True
        assert report.error_code is None
        assert report.workers["busy"].ready is True
        assert iteration_entered.wait(0.5)
        health = runtime.worker_health_snapshot()["workers"]["busy"]
        assert health["running"] is True
        assert health["last_failure_code"] == "database_busy"
    finally:
        _join_workers(runtime)


def test_owned_worker_restarts_after_ready_runtime_exit_and_recovers_phase(
    temp_db,
    monkeypatch,
) -> None:
    runtime = _owned_runtime()
    runtime.phase = RuntimePhase.RUNNING
    monkeypatch.setattr(app_runtime, "_WORKER_RESTART_INITIAL_SECONDS", 0.01)
    monkeypatch.setattr(app_runtime, "_WORKER_RESTART_MAX_SECONDS", 0.02)

    collector_stop = threading.Event()
    collector_thread = threading.Thread(
        target=collector_stop.wait,
        args=(2.0,),
        daemon=True,
    )
    collector_thread.start()
    runtime._collector_thread = collector_thread
    runtime._collector_stop_event = collector_stop

    attempts = 0
    recovered = threading.Event()

    def flaky_worker(stop_event, *, health):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic worker exit")
        health.succeeded()
        recovered.set()
        stop_event.wait(1.0)

    runtime._worker_specs = {
        "flaky": WorkerSpec(
            name="flaky",
            thread_name="WorkTraceFlakyWorker",
            target=flaky_worker,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.2,
        )
    }

    try:
        report = runtime.start_background_workers()

        assert report.ready is True
        assert recovered.wait(0.5)
        assert attempts == 2
        assert runtime.phase is RuntimePhase.RUNNING
        snapshot = runtime.worker_health_snapshot()
        assert snapshot["degraded_workers"] == []
        assert snapshot["workers"]["flaky"]["last_failure_code"] == ""
        assert snapshot["workers"]["flaky"]["consecutive_failures"] == 0
    finally:
        _join_workers(runtime)
        collector_stop.set()
        collector_thread.join(timeout=1.0)


def test_runtime_shutdown_cancels_pending_worker_restart(temp_db, monkeypatch) -> None:
    runtime = _owned_runtime()
    monkeypatch.setattr(app_runtime, "_WORKER_RESTART_INITIAL_SECONDS", 0.2)
    first_exit = threading.Event()
    attempts = 0

    def always_fails(_stop_event, *, health):
        nonlocal attempts
        attempts += 1
        first_exit.set()
        raise RuntimeError("synthetic worker exit")

    runtime._worker_specs = {
        "failing": WorkerSpec(
            name="failing",
            thread_name="WorkTraceFailingWorker",
            target=always_fails,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.2,
        )
    }

    report = runtime.start_background_workers()
    assert report.ready is True
    assert first_exit.wait(0.5)

    _join_workers(runtime)

    assert attempts == 1
