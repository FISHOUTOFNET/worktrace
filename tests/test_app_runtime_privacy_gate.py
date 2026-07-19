"""Direct contracts for AppRuntime ownership, startup and privacy gating."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime as runtime_module
from worktrace.runtime.app_runtime import AppRuntime, RuntimePhase, RuntimeStartResult

pytestmark = [
    pytest.mark.collector_runtime,
    pytest.mark.integration,
    pytest.mark.security_privacy,
    pytest.mark.serial,
    pytest.mark.db,
    pytest.mark.contract,
]


class _Thread:
    def __init__(
        self,
        *,
        target=None,
        args=(),
        name: str = "",
        daemon: bool = False,
        fail_start: bool = False,
    ) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        self.fail_start = fail_start
        self.alive = False
        self.start_calls = 0
        self.join_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_start:
            raise RuntimeError(f"failed to start {self.name}")
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout=None) -> None:
        self.join_calls += 1
        self.alive = False


class _ThreadFactory:
    def __init__(self, fail_names: set[str] | None = None) -> None:
        self.fail_names = set(fail_names or set())
        self.created: list[_Thread] = []

    def __call__(self, *, target=None, args=(), name="", daemon=False):
        thread = _Thread(
            target=target,
            args=args,
            name=name,
            daemon=daemon,
            fail_start=name in self.fail_names,
        )
        self.created.append(thread)
        return thread


def _paths(temp_db, tmp_path):
    return type(
        "Paths",
        (),
        {"db_path": str(temp_db), "log_path": str(tmp_path / "test.log")},
    )()


def _owned_runtime(temp_db, tmp_path, monkeypatch) -> AppRuntime:
    monkeypatch.setattr(runtime_module, "acquire_single_instance", lambda: True)
    monkeypatch.setattr(runtime_module, "release_single_instance", lambda: None)
    runtime = AppRuntime(_paths(temp_db, tmp_path), adapter=FakeAdapter())
    assert runtime.initialize() is True
    return runtime


def _install_thread_factory(monkeypatch, fail_names: set[str] | None = None):
    factory = _ThreadFactory(fail_names)
    monkeypatch.setattr(runtime_module.threading, "Thread", factory)
    return factory


def test_initialize_does_not_start_any_background_worker(
    temp_db,
    tmp_path,
    monkeypatch,
):
    factory = _install_thread_factory(monkeypatch)
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        assert factory.created == []
    finally:
        runtime.shutdown()


def test_start_background_workers_starts_each_owned_worker_once(
    temp_db,
    tmp_path,
    monkeypatch,
):
    factory = _install_thread_factory(monkeypatch)
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        first = runtime.start_background_workers()
        second = runtime.start_background_workers()

        assert first.ready is True
        assert first.started_any is True
        assert second.ready is True
        assert second.started_any is False
        assert [thread.name for thread in factory.created] == [
            "WorkTraceFolderIndex",
            "WorkTraceHistoryMutation",
            "WorkTraceInferenceWorker",
            "WorkTraceActivityResourceRepair",
            "WorkTraceStartupRecovery",
        ]
        assert all(thread.start_calls == 1 for thread in factory.created)
    finally:
        runtime.shutdown()


def test_background_worker_failure_identifies_exact_worker(
    temp_db,
    tmp_path,
    monkeypatch,
):
    _install_thread_factory(monkeypatch, {"WorkTraceFolderIndex"})
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        result = runtime.start_background_workers()
        assert result.ready is False
        assert result.failed_workers == ("folder_index",)
        assert result.error == "worker_start_failed"
        assert result.history_ready is True
        assert result.inference_ready is True
        assert result.resource_repair_ready is True
        assert result.startup_recovery_ready is True
    finally:
        runtime.shutdown()


def test_authorized_start_orders_collector_before_derived_workers(
    temp_db,
    tmp_path,
    monkeypatch,
):
    _install_thread_factory(monkeypatch)
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: order.append("collector")
        or {"ok": True, "started": True, "already_running": False},
    )
    original = runtime.start_background_workers

    def workers():
        order.append("workers")
        return original()

    monkeypatch.setattr(runtime, "start_background_workers", workers)
    try:
        result = runtime.start_authorized_collection()
        assert result.ok is True
        assert result.collector_ready is True
        assert result.degraded is False
        assert order == ["collector", "workers"]
    finally:
        runtime.shutdown()


def test_collector_failure_does_not_start_derived_workers(
    temp_db,
    tmp_path,
    monkeypatch,
):
    factory = _install_thread_factory(monkeypatch)
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: {"ok": False, "error": "collector_start_failed"},
    )
    try:
        result = runtime.start_authorized_collection()
        assert result.ok is False
        assert result.collector_ready is False
        assert result.error_code == "collector_start_failed"
        assert factory.created == []
        assert runtime.phase is RuntimePhase.RECOVERABLE_FAILURE
    finally:
        runtime.shutdown()


def test_derived_failure_degrades_runtime_without_relabeling_collector_failure(
    temp_db,
    tmp_path,
    monkeypatch,
):
    _install_thread_factory(monkeypatch, {"WorkTraceHistoryMutation"})
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: {"ok": True, "started": True, "already_running": False},
    )
    try:
        result = runtime.start_authorized_collection()
        assert result.ok is True
        assert result.collector_ready is True
        assert result.degraded is True
        assert result.error_code is None
        assert result.failed_workers == ("history",)
        assert runtime.phase is RuntimePhase.DEGRADED
    finally:
        runtime.shutdown()


def test_shutdown_stops_and_joins_all_derived_workers(
    temp_db,
    tmp_path,
    monkeypatch,
):
    factory = _install_thread_factory(monkeypatch)
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    runtime.start_background_workers()

    runtime.shutdown()

    assert runtime.stop_event.is_set()
    assert len(factory.created) == 5
    assert all(thread.join_calls == 1 for thread in factory.created)
    assert all(thread.alive is False for thread in factory.created)
    assert runtime._index_thread is None
    assert runtime._history_thread is None
    assert runtime._inference_thread is None
    assert runtime._resource_repair_thread is None
    assert runtime._startup_recovery_thread is None


def test_non_windows_default_adapter_fails_closed(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="unsupported_platform"):
        runtime_module._choose_adapter()


def test_non_windows_explicit_fake_adapter_remains_testable(
    temp_db,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(sys, "platform", "linux")
    runtime = AppRuntime(_paths(temp_db, tmp_path), adapter=FakeAdapter())
    assert isinstance(runtime._adapter, FakeAdapter)


def _recording_runtime(result: RuntimeStartResult):
    calls: list[str] = []

    def start_authorized_collection(self):
        calls.append("authorized_start")
        return result

    runtime = type(
        "RecordingRuntime",
        (),
        {"start_authorized_collection": start_authorized_collection},
    )()
    return runtime, calls


def test_privacy_gate_fails_closed_without_starting_runtime(monkeypatch):
    from worktrace.api import app_api

    runtime, calls = _recording_runtime(
        RuntimeStartResult(True, True, True, True)
    )
    monkeypatch.setattr(app_api, "_runtime", runtime)
    monkeypatch.setattr(
        "worktrace.services.privacy_gate_service.is_sensitive_runtime_allowed",
        lambda: False,
    )
    assert app_api.start_collection_after_privacy_gate() == {
        "ok": False,
        "error": "请先确认隐私说明",
    }
    assert calls == []


def test_privacy_gate_returns_structured_runtime_degradation(monkeypatch):
    from worktrace.api import app_api

    runtime, calls = _recording_runtime(
        RuntimeStartResult(
            ok=True,
            collector_ready=True,
            folder_index_ready=False,
            history_worker_ready=True,
            inference_worker_ready=True,
            resource_repair_worker_ready=True,
            startup_recovery_worker_ready=True,
            degraded=True,
            failed_workers=("folder_index",),
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
    assert result["failed_workers"] == ["folder_index"]


def test_worker_lifecycle_owner_remains_app_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime_source = (root / "worktrace/runtime/app_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "threading.Thread(" in runtime_source
    assert "activity_lifecycle_service.close_all_open_activities" in runtime_source
    for relative in (
        "worktrace/services/folder_index_service.py",
        "worktrace/services/history_mutation_job_service.py",
        "worktrace/services/activity_inference_job_service.py",
        "worktrace/services/activity_fact_repair_service.py",
        "worktrace/services/recovery_service.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "_WORKER_THREAD" not in source
        assert "threading.Thread(" not in source
