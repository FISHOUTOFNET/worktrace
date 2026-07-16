from types import SimpleNamespace

import pytest

from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import AppRuntime, RuntimePhase

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
    assert runtime.phase is RuntimePhase.FAILED
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
    assert runtime.phase is RuntimePhase.FAILED
    assert runtime.stop_event.is_set()
    assert runtime._collector_thread is None
