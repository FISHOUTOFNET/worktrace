from __future__ import annotations

import threading
import time
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


def _attach_live_collector(runtime: AppRuntime):
    collector_stop = threading.Event()
    collector_thread = threading.Thread(
        target=collector_stop.wait,
        args=(2.0,),
        daemon=True,
    )
    collector_thread.start()
    runtime._collector_thread = collector_thread
    runtime._collector_stop_event = collector_stop
    return collector_stop, collector_thread


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
        assert runtime._worker_handles["busy"].serving_event.is_set() is False
    finally:
        _join_workers(runtime)


def test_first_iteration_failure_degrades_before_failure_threshold(temp_db) -> None:
    runtime = _owned_runtime()
    runtime.phase = RuntimePhase.STARTING
    collector_stop, collector_thread = _attach_live_collector(runtime)
    failed = threading.Event()

    def fails_before_serving(stop_event, *, health):
        health.failed("database_busy")
        failed.set()
        stop_event.wait(1.0)

    runtime._worker_specs = {
        "busy": WorkerSpec(
            name="busy",
            thread_name="WorkTraceBusyWorker",
            target=fails_before_serving,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.2,
        )
    }

    try:
        report = runtime.start_background_workers()
        assert report.ready is True
        assert failed.wait(0.5)
        assert runtime.phase is RuntimePhase.DEGRADED
        snapshot = runtime.worker_health_snapshot()["workers"]["busy"]
        assert snapshot["consecutive_failures"] == 1
        assert runtime._worker_handles["busy"].serving_event.is_set() is False
    finally:
        _join_workers(runtime)
        collector_stop.set()
        collector_thread.join(timeout=1.0)


def test_starting_runtime_converges_only_after_worker_serves(temp_db) -> None:
    runtime = _owned_runtime()
    runtime.phase = RuntimePhase.STARTING
    collector_stop, collector_thread = _attach_live_collector(runtime)
    allow_success = threading.Event()
    served = threading.Event()

    def delayed_success(stop_event, *, health):
        allow_success.wait(1.0)
        health.succeeded()
        served.set()
        stop_event.wait(1.0)

    runtime._worker_specs = {
        "delayed": WorkerSpec(
            name="delayed",
            thread_name="WorkTraceDelayedWorker",
            target=delayed_success,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.2,
        )
    }

    try:
        report = runtime.start_background_workers()
        assert report.ready is True
        runtime._reconcile_worker_health_phase()
        assert runtime.phase is RuntimePhase.STARTING
        assert runtime._worker_handles["delayed"].serving_event.is_set() is False

        allow_success.set()
        assert served.wait(0.5)
        assert runtime.phase is RuntimePhase.RUNNING
        assert runtime._worker_handles["delayed"].serving_event.is_set() is True
    finally:
        _join_workers(runtime)
        collector_stop.set()
        collector_thread.join(timeout=1.0)


def test_restart_backoff_cannot_be_washed_back_to_running_by_peer_success(
    temp_db,
    monkeypatch,
) -> None:
    runtime = _owned_runtime()
    runtime.phase = RuntimePhase.RUNNING
    monkeypatch.setattr(app_runtime, "_WORKER_RESTART_INITIAL_SECONDS", 0.2)
    monkeypatch.setattr(app_runtime, "_WORKER_RESTART_MAX_SECONDS", 0.2)
    collector_stop, collector_thread = _attach_live_collector(runtime)

    flaky_attempts = 0
    crashed = threading.Event()
    recovered = threading.Event()
    peer_refresh = threading.Event()
    peer_refreshed = threading.Event()

    def flaky_worker(stop_event, *, health):
        nonlocal flaky_attempts
        flaky_attempts += 1
        if flaky_attempts == 1:
            health.succeeded()
            crashed.set()
            raise RuntimeError("synthetic worker exit")
        health.succeeded()
        recovered.set()
        stop_event.wait(1.0)

    def healthy_peer(stop_event, *, health):
        health.succeeded()
        while not stop_event.is_set():
            if peer_refresh.wait(0.01):
                peer_refresh.clear()
                health.succeeded()
                peer_refreshed.set()
            stop_event.wait(0.01)

    runtime._worker_specs = {
        "flaky": WorkerSpec(
            name="flaky",
            thread_name="WorkTraceFlakyWorker",
            target=flaky_worker,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.2,
        ),
        "peer": WorkerSpec(
            name="peer",
            thread_name="WorkTracePeerWorker",
            target=healthy_peer,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.2,
        ),
    }

    try:
        report = runtime.start_background_workers()
        assert report.ready is True
        assert crashed.wait(0.5)

        deadline = time.monotonic() + 0.5
        while runtime.phase is not RuntimePhase.DEGRADED and time.monotonic() < deadline:
            time.sleep(0.005)
        assert runtime.phase is RuntimePhase.DEGRADED
        assert runtime._worker_handles["flaky"].serving_event.is_set() is False

        peer_refresh.set()
        assert peer_refreshed.wait(0.5)
        assert runtime.phase is RuntimePhase.DEGRADED
        assert recovered.wait(0.5)
        assert flaky_attempts == 2
        assert runtime.phase is RuntimePhase.RUNNING
    finally:
        _join_workers(runtime)
        collector_stop.set()
        collector_thread.join(timeout=1.0)


def test_owned_worker_restarts_after_ready_runtime_exit_and_recovers_phase(
    temp_db,
    monkeypatch,
) -> None:
    runtime = _owned_runtime()
    runtime.phase = RuntimePhase.RUNNING
    monkeypatch.setattr(app_runtime, "_WORKER_RESTART_INITIAL_SECONDS", 0.01)
    monkeypatch.setattr(app_runtime, "_WORKER_RESTART_MAX_SECONDS", 0.02)

    collector_stop, collector_thread = _attach_live_collector(runtime)

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
