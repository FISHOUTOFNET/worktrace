from types import SimpleNamespace
import threading

import pytest

from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import (
    AppRuntime,
    RuntimePhase,
    WorkerSpec,
    WorkerStartupReport,
)
from worktrace.runtime.contracts import WorkerStartupState, WorkerStartupStatus

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def _owned_runtime() -> AppRuntime:
    runtime = AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=FakeAdapter(),
    )
    runtime.owns_application_instance = True
    return runtime


def test_collector_startup_failure_is_not_reported_ready(temp_db, monkeypatch):
    runtime = _owned_runtime()

    def fail_startup(
        _adapter,
        _stop_event,
        _control,
        _startup_ready_event,
        startup_failed_event,
    ):
        startup_failed_event.set()

    monkeypatch.setattr(app_runtime, "run_collector", fail_startup)

    result = runtime.start_collector(startup_timeout_seconds=0.2)

    assert result == {"ok": False, "error": "collector_start_failed"}
    assert runtime.phase is RuntimePhase.RECOVERABLE_FAILURE
    assert runtime._collector_thread is None


def test_live_thread_without_ready_handshake_times_out_closed(temp_db, monkeypatch):
    runtime = _owned_runtime()

    def never_ready(
        _adapter,
        stop_event,
        _control,
        _startup_ready_event,
        _startup_failed_event,
    ):
        stop_event.wait(1)

    monkeypatch.setattr(app_runtime, "run_collector", never_ready)

    result = runtime.start_collector(startup_timeout_seconds=0.1)

    assert result == {"ok": False, "error": "collector_start_failed"}
    assert runtime.phase is RuntimePhase.RECOVERABLE_FAILURE
    assert runtime.stop_event.is_set() is False
    assert runtime._collector_thread is None


def test_background_workers_launch_before_waiting_for_readiness(temp_db):
    runtime = _owned_runtime()
    runtime._initialized = True
    barrier = threading.Barrier(3)

    def coordinated_worker(stop_event, *, health):
        try:
            barrier.wait(timeout=1.0)
        except threading.BrokenBarrierError:
            health.failed("workers_started_serially")
            return
        health.succeeded()
        stop_event.wait(1.0)

    runtime._worker_specs = {
        f"worker_{index}": WorkerSpec(
            name=f"worker_{index}",
            thread_name=f"WorkTraceTestWorker{index}",
            target=coordinated_worker,
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.5,
        )
        for index in range(3)
    }

    try:
        report = runtime.start_background_workers()

        assert report.ready is True
        assert report.error_code is None
        assert tuple(report.workers) == ("worker_0", "worker_1", "worker_2")
        assert all(status.ready for status in report.workers.values())
    finally:
        runtime.request_shutdown()
        for handle in list(runtime._worker_handles.values()):
            if handle.thread is not None:
                handle.thread.join(timeout=1.0)


def test_authorized_start_skips_derived_workers_when_collector_fails(
    temp_db,
    monkeypatch,
):
    runtime = _owned_runtime()
    runtime._initialized = True
    order: list[str] = []
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: order.append("collector")
        or {"ok": False, "error": "collector_start_failed"},
    )
    monkeypatch.setattr(
        runtime,
        "start_background_workers",
        lambda: order.append("workers") or WorkerStartupReport({}),
    )

    result = runtime.start_authorized_collection()

    assert order == ["collector"]
    assert result.ok is False
    assert result.collector_ready is False
    assert result.workers == {}
    assert result.error_code == "collector_start_failed"
    assert runtime.phase is RuntimePhase.RECOVERABLE_FAILURE


def test_derived_worker_failure_degrades_ready_collector(
    temp_db,
    monkeypatch,
):
    runtime = _owned_runtime()
    runtime._initialized = True
    order: list[str] = []
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: order.append("collector")
        or {"ok": True, "started": True, "already_running": False},
    )
    statuses = {
        "folder_index": WorkerStartupStatus(
            WorkerStartupState.FAILED,
            False,
            error_code="worker_startup_failed",
        ),
        "history": WorkerStartupStatus(WorkerStartupState.READY, True, started=True),
        "inference": WorkerStartupStatus(WorkerStartupState.READY, True, started=True),
        "activity_resource_repair": WorkerStartupStatus(
            WorkerStartupState.READY,
            True,
            started=True,
        ),
        "startup_recovery": WorkerStartupStatus(
            WorkerStartupState.READY,
            True,
            started=True,
        ),
    }
    monkeypatch.setattr(
        runtime,
        "start_background_workers",
        lambda: order.append("workers")
        or WorkerStartupReport(statuses, "worker_start_failed"),
    )

    result = runtime.start_authorized_collection()

    assert order == ["collector", "workers"]
    assert result.ok is True
    assert result.collector_ready is True
    assert result.workers == statuses
    assert result.failed_workers == ("folder_index",)
    assert result.degraded is True
    assert result.error_code is None
    assert runtime.phase is RuntimePhase.DEGRADED
