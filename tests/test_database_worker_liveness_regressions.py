from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from worktrace.services import folder_index_runtime_service, recovery_service


pytestmark = [pytest.mark.unit, pytest.mark.collector_runtime, pytest.mark.db]


class _Health:
    def __init__(self) -> None:
        self.successes = 0
        self.failures: list[str] = []
        self.pauses: list[bool] = []

    def succeeded(self) -> None:
        self.successes += 1

    def failed(self, code: str) -> None:
        self.failures.append(str(code))

    def maintenance_paused(self, paused: bool) -> None:
        self.pauses.append(bool(paused))


class _Stop:
    def __init__(self) -> None:
        self.stopped = False

    def is_set(self) -> bool:
        return self.stopped

    def wait(self, _timeout: float | None = None) -> bool:
        return self.stopped

    def set(self) -> None:
        self.stopped = True


def test_folder_worker_does_not_run_startup_reconciliation_while_write_gate_blocked(
    monkeypatch,
) -> None:
    stop = _Stop()
    health = _Health()
    preflight_calls: list[str] = []

    def blocked() -> bool:
        stop.set()
        return True

    monkeypatch.setattr(
        folder_index_runtime_service.DATABASE_WRITE_GATE,
        "writes_blocked",
        blocked,
    )
    monkeypatch.setattr(folder_index_runtime_service._core, "_wait_for_worker", lambda: None)
    monkeypatch.setattr(
        folder_index_runtime_service,
        "ensure_index_states_for_folder_rules",
        lambda: preflight_calls.append("ensure"),
    )
    monkeypatch.setattr(
        folder_index_runtime_service._core,
        "recover_interrupted_indexes",
        lambda: preflight_calls.append("recover"),
    )
    monkeypatch.setattr(
        folder_index_runtime_service,
        "reconcile_index_eligibility",
        lambda: preflight_calls.append("reconcile"),
    )
    monkeypatch.setattr(
        folder_index_runtime_service,
        "validate_ready_indexes",
        lambda _stop: preflight_calls.append("validate"),
    )

    folder_index_runtime_service.run_folder_index_worker(stop, health=health)

    assert preflight_calls == []
    assert health.pauses == [True]
    assert health.successes == 0
    assert health.failures == []


def test_folder_worker_retries_startup_database_busy_inside_same_target(
    monkeypatch,
) -> None:
    stop = _Stop()
    health = _Health()
    ensure_attempts = 0

    def ensure() -> None:
        nonlocal ensure_attempts
        ensure_attempts += 1
        if ensure_attempts == 1:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        folder_index_runtime_service.DATABASE_WRITE_GATE,
        "writes_blocked",
        lambda: False,
    )
    monkeypatch.setattr(
        folder_index_runtime_service.privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )
    monkeypatch.setattr(folder_index_runtime_service._core, "_wait_for_worker", lambda: None)
    monkeypatch.setattr(
        folder_index_runtime_service,
        "ensure_index_states_for_folder_rules",
        ensure,
    )
    monkeypatch.setattr(
        folder_index_runtime_service._core,
        "recover_interrupted_indexes",
        lambda: 0,
    )
    monkeypatch.setattr(
        folder_index_runtime_service,
        "reconcile_index_eligibility",
        lambda: 0,
    )

    def validate(_stop) -> None:
        return None

    monkeypatch.setattr(
        folder_index_runtime_service,
        "validate_ready_indexes",
        validate,
    )

    def reconcile():
        stop.set()
        return (
            folder_index_runtime_service.folder_index_maintenance_service.FolderReconciliationOutcome()
        )

    monkeypatch.setattr(
        folder_index_runtime_service.folder_index_maintenance_service,
        "reconcile_open_unclassified_activities_outcome",
        reconcile,
    )

    folder_index_runtime_service.run_folder_index_worker(stop, health=health)

    assert ensure_attempts == 2
    assert health.failures == ["database_busy"]
    assert health.successes == 1


def test_startup_recovery_database_busy_during_job_discovery_is_iteration_failure(
    monkeypatch,
) -> None:
    stop = _Stop()
    health = _Health()
    connection_attempts = 0

    @contextmanager
    def fake_connection():
        nonlocal connection_attempts
        connection_attempts += 1
        if connection_attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        yield object()

    def no_jobs(_conn, *, limit: int):
        assert limit == 1
        stop.set()
        return []

    monkeypatch.setattr(recovery_service, "get_connection", fake_connection)
    monkeypatch.setattr(
        recovery_service.startup_recovery_job_repository,
        "list_runnable_jobs",
        no_jobs,
    )
    monkeypatch.setattr(
        recovery_service.DATABASE_WRITE_GATE,
        "writes_blocked",
        lambda: False,
    )

    recovery_service.run_startup_recovery_worker(
        stop,
        health=health,
        poll_seconds=0.1,
    )

    assert connection_attempts == 2
    assert health.failures == ["database_busy"]
    assert health.successes == 1
