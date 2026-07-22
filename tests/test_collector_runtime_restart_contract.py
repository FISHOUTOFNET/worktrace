import threading
from types import SimpleNamespace

import pytest

from worktrace.collector import collector_health
from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import AppRuntime
from worktrace.services import settings_service

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def _runtime() -> AppRuntime:
    return AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=FakeAdapter(),
    )


def test_start_collector_replaces_dead_thread_and_returns_structured_success(
    temp_db,
    monkeypatch,
):
    runtime = _runtime()
    runtime.owns_application_instance = True

    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join(timeout=1)
    assert not dead.is_alive(), "dead collector thread did not terminate"
    runtime._collector_thread = dead

    def fake_run_collector(
        _adapter,
        stop_event,
        _control,
        startup_ready_event,
        _startup_failed_event,
    ):
        collector_health.record_collector_started()
        startup_ready_event.set()
        stop_event.wait(1)

    monkeypatch.setattr(app_runtime, "run_collector", fake_run_collector)

    result = runtime.start_collector()
    try:
        assert result == {
            "ok": True,
            "started": True,
            "already_running": False,
        }
        assert runtime._collector_thread is not None
        assert runtime._collector_thread is not dead
        assert runtime._collector_thread.is_alive()
        assert (
            settings_service.get_setting("collector_last_failure_kind")
            == "thread_dead_replaced"
        )
        assert settings_service.get_setting("collector_status") == "running"
        assert (
            settings_service.get_setting("collector_health_state")
            == "healthy"
        )
    finally:
        runtime.request_shutdown()
        runtime._collector_thread.join(timeout=2)
        assert not runtime._collector_thread.is_alive(), "collector thread did not terminate on shutdown"


def test_start_collector_reports_not_owned_and_stopping(temp_db):
    runtime = _runtime()

    assert runtime.start_collector() == {
        "ok": False,
        "error": "collector_not_owned",
    }

    runtime.owns_application_instance = True
    runtime.stop_event.set()
    assert runtime.start_collector() == {
        "ok": False,
        "error": "runtime_stopping",
    }


def test_collector_start_failure_is_retryable_without_stopping_runtime(
    temp_db,
    monkeypatch,
):
    runtime = _runtime()
    runtime.owns_application_instance = True
    attempts = {"count": 0}

    def fake_run_collector(
        _adapter,
        stop_event,
        _control,
        startup_ready_event,
        startup_failed_event,
    ):
        attempts["count"] += 1
        if attempts["count"] == 1:
            startup_failed_event.set()
            return
        startup_ready_event.set()
        stop_event.wait(2)

    monkeypatch.setattr(app_runtime, "run_collector", fake_run_collector)

    first = runtime.start_collector(startup_timeout_seconds=0.2)
    assert first == {"ok": False, "error": "collector_start_failed"}
    assert runtime.stop_event.is_set() is False
    assert runtime.phase is app_runtime.RuntimePhase.RECOVERABLE_FAILURE

    second = runtime.start_collector(startup_timeout_seconds=0.5)
    try:
        assert second == {
            "ok": True,
            "started": True,
            "already_running": False,
        }
        assert attempts["count"] == 2
    finally:
        runtime.request_shutdown()
        assert runtime._collector_thread is not None
        runtime._collector_thread.join(timeout=2)
        assert not runtime._collector_thread.is_alive(), "collector thread did not terminate on shutdown"
