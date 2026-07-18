"""Direct contracts for AppRuntime ownership, startup and privacy gating."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime as runtime_module
from worktrace.runtime.app_runtime import AppRuntime, RuntimeStartResult
from worktrace.services import (
    activity_inference_job_service,
    folder_index_service,
    history_mutation_job_service,
)

pytestmark = [
    pytest.mark.collector_runtime,
    pytest.mark.integration,
    pytest.mark.security_privacy,
    pytest.mark.serial,
    pytest.mark.db,
    pytest.mark.contract,
]


class _Thread:
    def __init__(self) -> None:
        self.alive = True
        self.join_calls = 0

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout=None) -> None:
        self.join_calls += 1
        self.alive = False


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


def test_initialize_does_not_start_any_background_worker(
    temp_db,
    tmp_path,
    monkeypatch,
):
    starts: list[str] = []
    monkeypatch.setattr(
        folder_index_service,
        "start_folder_index_worker",
        lambda _stop: starts.append("index"),
    )
    monkeypatch.setattr(
        history_mutation_job_service,
        "start_history_worker",
        lambda _stop: starts.append("history"),
    )
    monkeypatch.setattr(
        activity_inference_job_service,
        "start_inference_worker",
        lambda *_args, **_kwargs: starts.append("inference"),
    )
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        assert starts == []
    finally:
        runtime.shutdown()


def test_start_background_workers_starts_each_worker_once(
    temp_db,
    tmp_path,
    monkeypatch,
):
    calls = {"index": 0, "history": 0, "inference": 0}

    def start(name):
        def command(*_args, **_kwargs):
            calls[name] += 1
            return _Thread()

        return command

    monkeypatch.setattr(folder_index_service, "start_folder_index_worker", start("index"))
    monkeypatch.setattr(history_mutation_job_service, "start_history_worker", start("history"))
    monkeypatch.setattr(activity_inference_job_service, "start_inference_worker", start("inference"))
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        first = runtime.start_background_workers()
        second = runtime.start_background_workers()
        assert first.ready is True
        assert first.inference_ready is True
        assert first.started_any is True
        assert second.ready is True
        assert second.started_any is False
        assert calls == {"index": 1, "history": 1, "inference": 1}
    finally:
        runtime.shutdown()


def test_background_worker_failure_identifies_exact_worker(
    temp_db,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        folder_index_service,
        "start_folder_index_worker",
        lambda _stop: None,
    )
    monkeypatch.setattr(
        history_mutation_job_service,
        "start_history_worker",
        lambda _stop: _Thread(),
    )
    monkeypatch.setattr(
        activity_inference_job_service,
        "start_inference_worker",
        lambda *_args, **_kwargs: _Thread(),
    )
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    try:
        result = runtime.start_background_workers()
        assert result.ready is False
        assert result.failed_workers == ("folder_index",)
        assert result.error == "worker_start_failed"
    finally:
        runtime.shutdown()


def test_authorized_start_orders_collector_before_derived_workers(
    temp_db,
    tmp_path,
    monkeypatch,
):
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
        monkeypatch.setattr(folder_index_service, "start_folder_index_worker", lambda _stop: _Thread())
        monkeypatch.setattr(history_mutation_job_service, "start_history_worker", lambda _stop: _Thread())
        monkeypatch.setattr(activity_inference_job_service, "start_inference_worker", lambda *_a, **_k: _Thread())
        return original()

    monkeypatch.setattr(runtime, "start_background_workers", workers)
    try:
        result = runtime.start_authorized_collection()
        assert result.ok is True
        assert order == ["collector", "workers"]
    finally:
        runtime.shutdown()


def test_shutdown_stops_and_joins_inference_worker(
    temp_db,
    tmp_path,
    monkeypatch,
):
    inference = _Thread()
    monkeypatch.setattr(folder_index_service, "start_folder_index_worker", lambda _stop: _Thread())
    monkeypatch.setattr(history_mutation_job_service, "start_history_worker", lambda _stop: _Thread())
    monkeypatch.setattr(activity_inference_job_service, "start_inference_worker", lambda *_a, **_k: inference)
    runtime = _owned_runtime(temp_db, tmp_path, monkeypatch)
    runtime.start_background_workers()
    runtime.shutdown()
    assert runtime.stop_event.is_set()
    assert inference.join_calls == 1
    assert inference.alive is False


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


def test_shutdown_lifecycle_owner_remains_app_runtime() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "worktrace/runtime/app_runtime.py"
    ).read_text(encoding="utf-8")
    assert "activity_lifecycle_service.close_all_open_activities" in source
