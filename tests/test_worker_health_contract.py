from __future__ import annotations

from types import SimpleNamespace

import pytest

from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime.app_runtime import AppRuntime, RuntimePhase
from worktrace.worker_health import (
    DEFAULT_CONSECUTIVE_FAILURE_THRESHOLD,
    WorkerHealthRegistry,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.collector_runtime]


def test_registry_tracks_success_failure_pause_and_stopped_state() -> None:
    registry = WorkerHealthRegistry()
    reporter = registry.reporter("inference")

    reporter.started()
    reporter.succeeded()
    reporter.maintenance_paused(True)
    reporter.failed("database_busy")
    reporter.failed("database_busy")

    state = registry.snapshots()["inference"]
    assert state.started is True
    assert state.running is True
    assert state.maintenance_paused is True
    assert state.last_successful_iteration_at.endswith("Z")
    assert state.last_failure_code == "database_busy"
    assert state.consecutive_failures == 2
    assert registry.degraded_workers() == ()

    reporter.failed("database_busy")
    assert registry.degraded_workers() == ("inference",)
    reporter.succeeded()
    reporter.stopped()
    state = registry.snapshots()["inference"]
    assert state.running is False
    assert state.maintenance_paused is False
    assert state.consecutive_failures == 0


def test_public_worker_health_never_exposes_traceback_or_sensitive_path() -> None:
    registry = WorkerHealthRegistry()
    reporter = registry.reporter("history")
    reporter.started()
    reporter.failed("history_iteration_failed")

    public = registry.public_snapshot()["history"]
    assert set(public) == {
        "running",
        "maintenance_paused",
        "last_successful_iteration_at",
        "last_failure_code",
        "consecutive_failures",
    }
    serialized = repr(public)
    assert "Traceback" not in serialized
    assert "C:\\" not in serialized


def test_app_runtime_marks_unexpected_worker_exit_degraded() -> None:
    runtime = AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=FakeAdapter(),
    )
    runtime.phase = RuntimePhase.RUNNING

    runtime._run_owned_worker("folder_index", lambda *, health: None, ())

    snapshot = runtime.worker_health_snapshot()
    assert snapshot["degraded_workers"] == ["folder_index"]
    assert snapshot["workers"]["folder_index"]["running"] is False
    assert snapshot["workers"]["folder_index"]["last_failure_code"] == (
        "worker_unexpected_exit"
    )
    assert runtime.phase is RuntimePhase.DEGRADED


def test_consecutive_failure_threshold_is_small_and_deterministic() -> None:
    assert DEFAULT_CONSECUTIVE_FAILURE_THRESHOLD == 3
