"""Privacy-gate and structured runtime startup contracts."""

from __future__ import annotations
from tests.support import runtime_state_fixture

import threading
from unittest.mock import patch

import pytest

from worktrace.collector.collector import run_collector
from worktrace.runtime.app_runtime import (
    AppRuntime,
    RuntimeStartResult,
    WorkerReadiness,
)
from worktrace.services import (
    folder_index_service,
    runtime_activity_state_service,
    settings_service,
)

pytestmark = [
    pytest.mark.collector_runtime,
    pytest.mark.integration,
    pytest.mark.security_privacy,
    pytest.mark.serial,
    pytest.mark.db,
]


def _make_paths(temp_db, tmp_path):
    return type(
        "P",
        (),
        {
            "db_path": str(temp_db),
            "log_path": str(tmp_path / "test.log"),
        },
    )()


def _fake_thread():
    return type(
        "T",
        (),
        {
            "join": lambda self, timeout=None: None,
            "is_alive": lambda self: True,
        },
    )()


def _initialize_owned_runtime(temp_db, tmp_path, monkeypatch) -> AppRuntime:
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance",
        lambda: True,
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance",
        lambda: None,
    )
    runtime = AppRuntime(_make_paths(temp_db, tmp_path))
    runtime.initialize()
    return runtime


def test_initialize_does_not_start_folder_index_worker(
    temp_db,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance",
        lambda: True,
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance",
        lambda: None,
    )
    runtime = AppRuntime(_make_paths(temp_db, tmp_path))
    try:
        with patch(
            "worktrace.services.folder_index_service.start_folder_index_worker"
        ) as mock_start:
            runtime.initialize()
            mock_start.assert_not_called()
    finally:
        runtime.shutdown()


def test_start_background_workers_reports_first_start_and_existing_readiness(
    temp_db,
    tmp_path,
    monkeypatch,
):
    start_calls = {"index": 0, "history": 0}

    def start_index(_stop_event):
        start_calls["index"] += 1
        return _fake_thread()

    def start_history(_stop_event):
        start_calls["history"] += 1
        return _fake_thread()

    monkeypatch.setattr(
        folder_index_service,
        "start_folder_index_worker",
        start_index,
    )
    monkeypatch.setattr(
        "worktrace.services.history_mutation_job_service.start_history_worker",
        start_history,
    )
    runtime = _initialize_owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        first = runtime.start_background_workers()
        second = runtime.start_background_workers()

        assert first == WorkerReadiness(
            index_ready=True,
            history_ready=True,
            index_started=True,
            history_started=True,
            error=None,
        )
        assert second.ready is True
        assert second.started_any is False
        assert second.error is None
        assert start_calls == {"index": 1, "history": 1}
    finally:
        runtime.shutdown()


def test_start_background_workers_reports_not_owned(
    temp_db,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance",
        lambda: False,
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance",
        lambda: None,
    )
    runtime = AppRuntime(_make_paths(temp_db, tmp_path))
    try:
        assert runtime.initialize() is False
        result = runtime.start_background_workers()
        assert result.ready is False
        assert result.error == "runtime_not_owned"
    finally:
        runtime.shutdown()


def test_start_background_workers_reports_partial_failure(
    temp_db,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        folder_index_service,
        "start_folder_index_worker",
        lambda _stop_event: None,
    )
    monkeypatch.setattr(
        "worktrace.services.history_mutation_job_service.start_history_worker",
        lambda _stop_event: _fake_thread(),
    )
    runtime = _initialize_owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        result = runtime.start_background_workers()
        assert result.index_ready is False
        assert result.history_ready is True
        assert result.ready is False
        assert result.error == "worker_start_failed"
    finally:
        runtime.shutdown()


def test_app_api_start_background_workers_has_explicit_no_runtime_result(
    monkeypatch,
):
    from worktrace.api import app_api

    monkeypatch.setattr(app_api, "_runtime", None)
    assert app_api.start_background_workers() == {
        "ready": False,
        "index_ready": False,
        "history_ready": False,
        "index_started": False,
        "history_started": False,
        "error": "runtime_not_registered",
    }


def _recording_runtime(result: RuntimeStartResult | None = None):
    calls: list[str] = []

    def start_authorized_collection(self):
        calls.append("authorized_start")
        return result or RuntimeStartResult(
            ok=True,
            collector_ready=True,
            folder_index_ready=True,
            history_worker_ready=True,
        )

    runtime = type(
        "R",
        (),
        {"start_authorized_collection": start_authorized_collection},
    )()
    return runtime, calls


def test_privacy_gate_fails_closed_without_touching_runtime(monkeypatch):
    from worktrace.api import app_api

    runtime, calls = _recording_runtime()
    monkeypatch.setattr(app_api, "_runtime", runtime)
    monkeypatch.setattr(
        "worktrace.services.privacy_gate_service.is_sensitive_runtime_allowed",
        lambda: False,
    )

    result = app_api.start_collection_after_privacy_gate()

    assert result == {"ok": False, "error": "请先确认隐私说明"}
    assert calls == []


def test_privacy_gate_fails_closed_when_notice_read_raises(monkeypatch):
    from worktrace.api import app_api

    runtime, calls = _recording_runtime()
    monkeypatch.setattr(app_api, "_runtime", runtime)

    def fail_read():
        raise RuntimeError("settings read failed")

    monkeypatch.setattr(
        "worktrace.services.privacy_gate_service.is_sensitive_runtime_allowed",
        fail_read,
    )

    result = app_api.start_collection_after_privacy_gate()

    assert result == {"ok": False, "error": "请先确认隐私说明"}
    assert calls == []


def test_privacy_gate_delegates_complete_startup_to_runtime(monkeypatch):
    from worktrace.api import app_api

    runtime, calls = _recording_runtime(
        RuntimeStartResult(
            ok=True,
            collector_ready=True,
            folder_index_ready=False,
            history_worker_ready=True,
            already_running=False,
            degraded=True,
        )
    )
    monkeypatch.setattr(app_api, "_runtime", runtime)
    monkeypatch.setattr(
        "worktrace.services.privacy_gate_service.is_sensitive_runtime_allowed",
        lambda: True,
    )

    result = app_api.start_collection_after_privacy_gate()

    assert calls == ["authorized_start"]
    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["folder_index_ready"] is False
    assert result["history_worker_ready"] is True


def test_privacy_gate_propagates_runtime_start_failure(monkeypatch):
    from worktrace.api import app_api

    runtime, _calls = _recording_runtime(
        RuntimeStartResult(
            ok=False,
            collector_ready=False,
            folder_index_ready=True,
            history_worker_ready=True,
            degraded=True,
            error_code="collector_start_failed",
        )
    )
    monkeypatch.setattr(app_api, "_runtime", runtime)
    monkeypatch.setattr(
        "worktrace.services.privacy_gate_service.is_sensitive_runtime_allowed",
        lambda: True,
    )

    result = app_api.start_collection_after_privacy_gate()

    assert result["ok"] is False
    assert result["error"] == "collector_start_failed"


def test_runtime_startup_orders_collector_before_derived_workers(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _initialize_owned_runtime(temp_db, tmp_path, monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.assignment_command_service.retry_pending_inference",
        lambda _limit: order.append("retry"),
    )
    monkeypatch.setattr(
        runtime,
        "start_background_workers",
        lambda: (
            order.append("workers")
            or WorkerReadiness(True, True, True, True)
        ),
    )
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: order.append("collector")
        or {"ok": True, "started": True, "already_running": False},
    )
    try:
        result = runtime.start_authorized_collection()
        assert result.ok is True
        assert result.degraded is False
        assert order == ["retry", "collector", "workers"]
    finally:
        runtime.shutdown()


def test_startup_recovery_runtime_cleanup_is_single_owner(
    temp_db,
    tmp_path,
    monkeypatch,
):
    calls: list[str] = []

    def recover_once():
        calls.append("runtime")
        runtime_activity_state_service.clear_runtime_activity_state(
            "test_startup"
        )

    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance",
        lambda: True,
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance",
        lambda: None,
    )
    monkeypatch.setattr(
        "worktrace.services.recovery_service.recover_unclosed_records",
        recover_once,
    )
    monkeypatch.setattr(
        "worktrace.collector.collector.clipboard_service.prune_old_events",
        lambda: None,
    )

    runtime_state_fixture.set_setting("current_activity_snapshot", '{"old": true}')
    runtime_state_fixture.set_setting("pending_short_seconds", "9")
    runtime = AppRuntime(_make_paths(temp_db, tmp_path))
    try:
        runtime.initialize()
        assert calls == ["runtime"]
        assert runtime_state_fixture.get_setting("current_activity_snapshot") == ""
        assert runtime_state_fixture.get_setting("pending_short_seconds") == "0"

        stop_event = threading.Event()
        stop_event.set()
        run_collector(type("Adapter", (), {})(), stop_event)
        assert calls == ["runtime"]
    finally:
        runtime.shutdown()


def test_non_owner_runtime_does_not_clear_owner_live_state(
    temp_db,
    tmp_path,
    monkeypatch,
):
    calls: list[str] = []
    close_calls: list[str] = []

    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance",
        lambda: False,
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance",
        lambda: calls.append("release"),
    )
    monkeypatch.setattr(
        "worktrace.services.recovery_service.recover_unclosed_records",
        lambda: calls.append("recovery"),
    )
    monkeypatch.setattr(
        "worktrace.services.activity_lifecycle_service.close_all_open_activities",
        lambda *args, **kwargs: close_calls.append("close"),
    )

    runtime_state_fixture.set_setting("current_activity_snapshot", '{"owner": true}')
    runtime_state_fixture.set_setting("pending_short_seconds", "11")
    runtime = AppRuntime(_make_paths(temp_db, tmp_path))

    runtime.initialize()
    runtime.shutdown()

    assert runtime.owns_application_instance is False
    assert calls == []
    assert close_calls == []
    assert runtime_state_fixture.get_setting("current_activity_snapshot") == '{"owner": true}'
    assert runtime_state_fixture.get_setting("pending_short_seconds") == "0"
