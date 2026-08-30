from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import AppRuntime, RuntimePhase, WorkerSpec


pytestmark = [pytest.mark.collector_runtime, pytest.mark.integration]


def _owned_runtime() -> AppRuntime:
    runtime = AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=FakeAdapter(),
    )
    runtime.owns_application_instance = True
    runtime._initialized = True
    runtime.phase = RuntimePhase.STARTING
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


def _shutdown_runtime(
    runtime: AppRuntime,
    collector_stop: threading.Event,
    collector_thread: threading.Thread,
) -> None:
    runtime.request_shutdown()
    for handle in list(runtime._worker_handles.values()):
        if handle.thread is not None:
            handle.thread.join(timeout=1.0)
    watchdog = runtime._worker_progress_watchdog_thread
    if watchdog is not None:
        watchdog.join(timeout=1.0)
    collector_stop.set()
    collector_thread.join(timeout=1.0)


def test_served_alive_worker_without_progress_degrades_without_second_owner(
    temp_db,
    monkeypatch,
) -> None:
    runtime = _owned_runtime()
    collector_stop, collector_thread = _attach_live_collector(runtime)
    monkeypatch.setattr(app_runtime, "_WORKER_PROGRESS_WATCHDOG_SECONDS", 0.01)

    served = threading.Event()
    resume = threading.Event()
    recovered = threading.Event()
    attempts = 0

    def stalled_worker(stop_event, *, health):
        nonlocal attempts
        attempts += 1
        health.succeeded()
        served.set()
        resume.wait(1.0)
        if stop_event.is_set():
            return
        health.succeeded()
        recovered.set()
        stop_event.wait(1.0)

    runtime._worker_specs = {
        "stalled": WorkerSpec(
            name="stalled",
            thread_name="WorkTraceStalledWorker",
            target=stalled_worker,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.2,
            progress_timeout_seconds=0.05,
        )
    }

    try:
        report = runtime.start_background_workers()
        assert report.ready is True
        assert served.wait(0.5)

        deadline = time.monotonic() + 0.5
        snapshot = runtime.worker_health_snapshot()
        while (
            "stalled" not in snapshot["degraded_workers"]
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
            snapshot = runtime.worker_health_snapshot()

        handle = runtime._worker_handles["stalled"]
        assert runtime.phase is RuntimePhase.DEGRADED
        assert snapshot["degraded_workers"] == ["stalled"]
        assert handle.thread is not None and handle.thread.is_alive()
        assert attempts == 1, "stalled-but-alive worker must retain its sole owner"

        resume.set()
        assert recovered.wait(0.5)
        deadline = time.monotonic() + 0.5
        while runtime.phase is not RuntimePhase.RUNNING and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runtime.phase is RuntimePhase.RUNNING
        assert runtime.worker_health_snapshot()["degraded_workers"] == []
        assert attempts == 1
    finally:
        resume.set()
        _shutdown_runtime(runtime, collector_stop, collector_thread)


def test_intentional_maintenance_pause_is_not_reported_as_progress_stall(
    temp_db,
    monkeypatch,
) -> None:
    runtime = _owned_runtime()
    collector_stop, collector_thread = _attach_live_collector(runtime)
    monkeypatch.setattr(app_runtime, "_WORKER_PROGRESS_WATCHDOG_SECONDS", 0.01)

    paused = threading.Event()

    def maintenance_worker(stop_event, *, health):
        health.succeeded()
        health.maintenance_paused(True)
        paused.set()
        stop_event.wait(1.0)

    runtime._worker_specs = {
        "maintenance": WorkerSpec(
            name="maintenance",
            thread_name="WorkTraceMaintenanceWorker",
            target=maintenance_worker,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.2,
            progress_timeout_seconds=0.03,
        )
    }

    try:
        report = runtime.start_background_workers()
        assert report.ready is True
        assert paused.wait(0.5)
        time.sleep(0.08)

        snapshot = runtime.worker_health_snapshot()
        assert snapshot["workers"]["maintenance"]["maintenance_paused"] is True
        assert snapshot["degraded_workers"] == []
        assert runtime.phase is RuntimePhase.RUNNING
    finally:
        _shutdown_runtime(runtime, collector_stop, collector_thread)
