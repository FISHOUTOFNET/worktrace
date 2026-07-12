import time
import threading
from types import SimpleNamespace

import pytest

from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import AppRuntime
from worktrace.services import settings_service

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def test_start_collector_replaces_dead_thread_and_returns_structured_success(temp_db, monkeypatch):
    runtime = AppRuntime(SimpleNamespace(db_path="", log_path=""))
    runtime.owns_collector = True

    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join(timeout=1)
    runtime._collector_thread = dead

    def fake_run_collector(_adapter, stop_event, _control):
        stop_event.wait(1)

    monkeypatch.setattr(app_runtime, "_choose_adapter", lambda: object())
    monkeypatch.setattr(app_runtime, "run_collector", fake_run_collector)

    result = runtime.start_collector()
    try:
        assert result == {"ok": True, "started": True, "already_running": False}
        assert runtime._collector_thread is not None
        assert runtime._collector_thread is not dead
        assert runtime._collector_thread.is_alive()
        assert settings_service.get_setting("collector_last_failure_kind") == "thread_dead_replaced"
        assert settings_service.get_setting("collector_status") == "running"
        assert settings_service.get_setting("collector_health_state") == "healthy"
    finally:
        runtime.stop_event.set()
        runtime._collector_thread.join(timeout=2)


def test_start_collector_reports_not_owned_and_stopping(temp_db):
    runtime = AppRuntime(SimpleNamespace(db_path="", log_path=""))

    assert runtime.start_collector() == {"ok": False, "error": "collector_not_owned"}

    runtime.owns_collector = True
    runtime.stop_event.set()
    assert runtime.start_collector() == {"ok": False, "error": "runtime_stopping"}
