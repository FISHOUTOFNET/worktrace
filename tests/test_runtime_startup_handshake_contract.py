from types import SimpleNamespace

import pytest

from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import (
    AppRuntime,
    RuntimePhase,
    WorkerReadiness,
)

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def _owned_runtime() -> AppRuntime:
    runtime = AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=object(),
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


def test_authorized_start_skips_derived_workers_when_collector_fails(
    temp_db,
    monkeypatch,
):
    runtime = _owned_runtime()
    runtime._initialized = True
    order: list[str] = []
    monkeypatch.setattr(
        app_runtime.assignment_command_service,
        "retry_pending_inference",
        lambda _limit: order.append("retry"),
    )
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: order.append("collector")
        or {"ok": False, "error": "collector_start_failed"},
    )
    monkeypatch.setattr(
        runtime,
        "start_background_workers",
        lambda: order.append("workers") or WorkerReadiness(True, True),
    )

    result = runtime.start_authorized_collection()

    assert order == ["retry", "collector"]
    assert result.ok is False
    assert result.collector_ready is False
    assert result.folder_index_ready is False
    assert result.history_worker_ready is False
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
        app_runtime.assignment_command_service,
        "retry_pending_inference",
        lambda _limit: order.append("retry"),
    )
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: order.append("collector")
        or {"ok": True, "started": True, "already_running": False},
    )
    monkeypatch.setattr(
        runtime,
        "start_background_workers",
        lambda: order.append("workers")
        or WorkerReadiness(
            index_ready=False,
            history_ready=True,
            history_started=True,
            error="worker_start_failed",
        ),
    )

    result = runtime.start_authorized_collection()

    assert order == ["retry", "collector", "workers"]
    assert result.ok is True
    assert result.collector_ready is True
    assert result.folder_index_ready is False
    assert result.history_worker_ready is True
    assert result.degraded is True
    assert runtime.phase is RuntimePhase.DEGRADED
