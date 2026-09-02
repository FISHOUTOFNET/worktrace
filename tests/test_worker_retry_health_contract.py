from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from worktrace.database_failure_policy import (
    DatabaseFailureKind,
    classify_database_failure,
)
from worktrace.services import activity_inference_job_service
from worktrace.services import folder_index_service
from worktrace.services import folder_index_runtime_service
from worktrace.services import history_mutation_job_service
from worktrace.worker_health import WorkerHealthRegistry, degraded_failure


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.db]


def test_database_failure_policy_classifies_busy_and_extended_busy() -> None:
    locked = sqlite3.OperationalError("database is locked")
    assert classify_database_failure(locked) is DatabaseFailureKind.BUSY

    extended = sqlite3.OperationalError("busy snapshot")
    extended.sqlite_errorcode = sqlite3.SQLITE_BUSY | (2 << 8)
    extended.sqlite_errorname = "SQLITE_BUSY_SNAPSHOT"
    assert classify_database_failure(extended) is DatabaseFailureKind.BUSY


def test_explicit_partial_failure_degrades_until_real_success() -> None:
    registry = WorkerHealthRegistry()
    reporter = registry.reporter("inference")
    reporter.started()
    reporter.succeeded()
    reporter.failed(degraded_failure("inference_job_failures"))

    assert registry.degraded_workers() == ("inference",)
    assert registry.snapshots()["inference"].last_failure_code == (
        "inference_job_failures"
    )

    reporter.maintenance_paused(False)
    assert registry.degraded_workers() == ("inference",)
    reporter.succeeded()
    assert registry.degraded_workers() == ()


def test_progress_refreshes_lease_without_clearing_degraded_failure() -> None:
    now = {"value": 10.0}
    registry = WorkerHealthRegistry(monotonic_func=lambda: now["value"])
    reporter = registry.reporter("inference")
    reporter.started()
    reporter.failed(degraded_failure("inference_job_failures"))

    before = registry.snapshots()["inference"]
    now["value"] = 25.0
    reporter.progressed()
    after = registry.snapshots()["inference"]

    assert before.last_failure_code == "inference_job_failures"
    assert after.last_failure_code == "inference_job_failures"
    assert after.explicit_degraded is True
    assert after.served is True
    assert after.last_progress_monotonic == 25.0
    assert registry.degraded_workers() == ("inference",)


def test_inference_batch_stops_after_first_database_busy(monkeypatch) -> None:
    runnable = [{"activity_id": value} for value in range(1, 51)]
    list_calls: list[int] = []

    @contextmanager
    def fake_connection():
        yield object()

    def fake_list(_conn, *, limit, activity_ids=None):
        list_calls.append(limit)
        if activity_ids is None:
            return runnable
        raise AssertionError(
            "per-job list should not run after UoW acquisition fails"
        )

    class BusyUow:
        def __enter__(self):
            raise sqlite3.OperationalError("database is locked")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        activity_inference_job_service,
        "get_connection",
        fake_connection,
    )
    monkeypatch.setattr(
        activity_inference_job_service.jobs,
        "list_runnable_jobs",
        fake_list,
    )
    monkeypatch.setattr(
        activity_inference_job_service,
        "DomainUnitOfWork",
        lambda *_args, **_kwargs: BusyUow(),
    )

    outcome = activity_inference_job_service._process_pending_inference_batch(
        lambda *_args: {},
        limit=50,
    )

    assert outcome.attempted == 1
    assert outcome.processed == 0
    assert outcome.infrastructure_failure is DatabaseFailureKind.BUSY
    assert list_calls == [50]


def test_folder_build_database_busy_is_not_permanent_error(
    monkeypatch,
    tmp_path,
) -> None:
    folder = tmp_path / "indexed"
    folder.mkdir()
    failures: list[tuple[int, int, str]] = []

    monkeypatch.setattr(
        folder_index_service,
        "_load_folder_rule",
        lambda _rule_id: {"folder_path": str(folder), "recursive": False},
    )
    monkeypatch.setattr(
        folder_index_service.privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )
    monkeypatch.setattr(
        folder_index_service,
        "_begin_generation",
        lambda _rule_id: (7, "now"),
    )

    def busy_iter(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")
        yield

    monkeypatch.setattr(folder_index_service, "_iter_files", busy_iter)
    monkeypatch.setattr(
        folder_index_service,
        "_fail_generation",
        lambda rule_id, generation, code: failures.append(
            (rule_id, generation, code)
        ),
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        folder_index_runtime_service._CORE_REBUILD_FOLDER_INDEX(3)
    assert failures == []


def test_history_database_busy_does_not_terminalize_job(monkeypatch) -> None:
    job = {"id": 4, "status": "pending", "kind": "rule_backfill"}
    terminal_failures: list[tuple[int, str]] = []

    monkeypatch.setattr(
        history_mutation_job_service,
        "_load_job",
        lambda _job_id: job,
    )
    monkeypatch.setattr(
        history_mutation_job_service,
        "_payload",
        lambda _job: {},
    )
    monkeypatch.setattr(
        history_mutation_job_service,
        "_folder_index_gate",
        lambda _job: "ready",
    )

    def busy(*_args):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        history_mutation_job_service,
        "_run_backfill_batch",
        busy,
    )
    monkeypatch.setattr(
        history_mutation_job_service,
        "_fail_job",
        lambda job_id, message: terminal_failures.append((job_id, message)),
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        history_mutation_job_service.run_job_batch(4)
    assert terminal_failures == []


def test_folder_worker_owner_is_explicit_not_lifecycle_monkeypatched() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime_source = (root / "worktrace/runtime/app_runtime.py").read_text(
        encoding="utf-8"
    )
    init_source = (root / "worktrace/services/__init__.py").read_text(
        encoding="utf-8"
    )

    assert "folder_index_runtime_service.run_folder_index_worker" in runtime_source
    assert '"run_folder_index_worker"' not in init_source
