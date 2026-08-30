"""Direct contracts for AppRuntime ownership, startup and privacy gating."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.support.application import TestMaintenance
from worktrace.api.app_api import ApplicationControlService
from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime as runtime_module
from worktrace.runtime.app_runtime import AppRuntime, RuntimePhase, WorkerSpec
from worktrace.runtime.contracts import (
    RuntimeStartResult,
    WorkerStartupState,
    WorkerStartupStatus,
)

pytestmark = [
    pytest.mark.collector_runtime,
    pytest.mark.integration,
    pytest.mark.security_privacy,
    pytest.mark.serial,
    pytest.mark.db,
    pytest.mark.contract,
]


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


def _install_blocking_test_specs(runtime: AppRuntime, *, failing: str | None = None) -> None:
    def target_for(name):
        def target(stop_event, *, health):
            if name == failing:
                health.failed("iteration_failed")
                stop_event.wait()
                return
            health.succeeded()
            stop_event.wait()

        return target

    runtime._worker_specs = {
        name: WorkerSpec(
            name=name,
            thread_name=spec.thread_name,
            target=target_for(name),
            args_factory=lambda stop: (stop,),
            startup_timeout_seconds=0.5,
        )
        for name, spec in runtime._worker_specs.items()
    }


def test_initialize_does_not_start_any_background_worker(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        assert runtime._worker_handles == {}
    finally:
        runtime.shutdown()


def test_worker_registry_contains_every_declared_runtime_worker(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        assert tuple(runtime._worker_specs) == (
            "clipboard_capture",
            "folder_index",
            "history",
            "inference",
            "activity_resource_repair",
            "startup_recovery",
            "collector_supervisor",
        )
        assert all(isinstance(spec, WorkerSpec) for spec in runtime._worker_specs.values())
    finally:
        runtime.shutdown()


def test_start_background_workers_starts_each_owned_worker_once(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    _install_blocking_test_specs(runtime)
    try:
        first = runtime.start_background_workers()
        second = runtime.start_background_workers()

        assert first.ready is True
        assert first.started_any is True
        assert second.ready is True
        assert second.started_any is False
        assert set(runtime._worker_handles) == set(runtime._worker_specs)
        assert all(status.state is WorkerStartupState.READY for status in first.workers.values())
    finally:
        runtime.shutdown()


def test_background_worker_iteration_failure_does_not_poison_startup_readiness(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    _install_blocking_test_specs(runtime, failing="folder_index")
    try:
        result = runtime.start_background_workers()
        assert result.ready is True
        assert result.failed_workers == ()
        assert result.error_code is None
        assert result.workers["folder_index"].state is WorkerStartupState.READY
        assert all(status.ready for status in result.workers.values())
        health = runtime.worker_health_snapshot()["workers"]["folder_index"]
        assert health["running"] is True
        assert health["last_failure_code"] == "iteration_failed"
    finally:
        runtime.shutdown()


def test_worker_thread_start_failure_remains_a_startup_failure(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    spec = next(iter(runtime._worker_specs.values()))

    def fail_start(_thread):
        raise RuntimeError("synthetic thread start failure")

    monkeypatch.setattr(runtime_module.threading.Thread, "start", fail_start)
    try:
        handle, started, status = runtime._start_worker(spec)
        assert handle is None
        assert started is False
        assert status is not None
        assert status.ready is False
        assert status.state is WorkerStartupState.FAILED
        assert status.error_code == "worker_thread_start_failed"
    finally:
        runtime.shutdown()


def test_authorized_start_orders_collector_before_derived_workers(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    _install_blocking_test_specs(runtime)
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
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    _install_blocking_test_specs(runtime)
    monkeypatch.setattr(
        runtime,
        "start_collector",
        lambda: {"ok": False, "error": "collector_start_failed"},
    )
    try:
        result = runtime.start_authorized_collection()
        assert result.ok is False
        assert result.collector_ready is False
        assert result.workers == {}
        assert result.error_code == "collector_start_failed"
        assert runtime._worker_handles == {}
        assert runtime.phase is RuntimePhase.RECOVERABLE_FAILURE
    finally:
        runtime.shutdown()


def test_shutdown_stops_and_joins_all_registry_workers(
    temp_db,
    tmp_path,
    monkeypatch,
):
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    _install_blocking_test_specs(runtime)
    runtime.start_background_workers()

    runtime.shutdown()

    assert runtime.stop_event.is_set()
    assert runtime._worker_handles == {}
    assert runtime.phase is RuntimePhase.STOPPED


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
    runtime, calls = _recording_runtime(
        RuntimeStartResult(True, True, {})
    )
    control = ApplicationControlService(runtime, TestMaintenance())
    monkeypatch.setattr(
        "worktrace.services.privacy_gate_service.is_sensitive_runtime_allowed",
        lambda: False,
    )
    assert control.start_collection_after_privacy_gate() == {
        "ok": False,
        "error": "请先确认隐私说明",
    }
    assert calls == []


def test_privacy_gate_returns_structured_runtime_degradation(monkeypatch):
    runtime, calls = _recording_runtime(
        RuntimeStartResult(
            ok=True,
            collector_ready=True,
            workers={
                "folder_index": WorkerStartupStatus(
                    WorkerStartupState.FAILED,
                    False,
                    error_code="worker_startup_failed",
                )
            },
            degraded=True,
        )
    )
    control = ApplicationControlService(runtime, TestMaintenance())
    monkeypatch.setattr(
        "worktrace.services.privacy_gate_service.is_sensitive_runtime_allowed",
        lambda: True,
    )
    result = control.start_collection_after_privacy_gate()
    assert calls == ["authorized_start"]
    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["workers"]["folder_index"]["state"] == "failed"


def test_worker_lifecycle_owner_remains_app_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime_source = (root / "worktrace/runtime/app_runtime.py").read_text(
        encoding="utf-8"
    )
    supervisor_source = (
        root / "worktrace/runtime/collector_supervisor.py"
    ).read_text(encoding="utf-8")
    assert "class WorkerSpec" in runtime_source
    assert "self._worker_handles" in runtime_source
    assert "threading.Thread(" in runtime_source
    assert '"collector_supervisor": WorkerSpec(' in runtime_source
    assert "target=self.collector_supervisor.run_worker" in runtime_source
    assert "threading.Thread(" not in supervisor_source
    assert "recovery_service.recover_unclosed_activity_facts(" in runtime_source
    assert "allow_legacy_heartbeat=False" in runtime_source
    assert "activity_lifecycle_service.close_all_open_activities" not in runtime_source
    for legacy_member in (
        "_index_thread",
        "_history_thread",
        "_inference_thread",
        "_resource_repair_thread",
        "_startup_recovery_thread",
    ):
        assert legacy_member not in runtime_source
