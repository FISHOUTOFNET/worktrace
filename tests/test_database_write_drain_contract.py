from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from worktrace.db import get_connection
from worktrace.services import database_maintenance_service, project_service, settings_service
from worktrace.services.database_maintenance_barrier import drain_existing_writers
from worktrace.services.database_maintenance_service import (
    MaintenancePhase,
    RuntimeMaintenanceCoordinator,
)
from worktrace.write_gate import DATABASE_WRITE_GATE, ProcessDatabaseWriteGate, WriteGatePhase

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


class _OperationalHoldState:
    value = "operational"


class _OperationalChannel:
    hold_state = _OperationalHoldState()

    def query_command(self, command_id: str):
        return None


class _RuntimeControl:
    def __init__(self, coordinator: RuntimeMaintenanceCoordinator) -> None:
        self.coordinator = coordinator
        self.observed: list[tuple[str, MaintenancePhase, WriteGatePhase]] = []
        self.writer_outcomes: list[tuple[str, str]] = []
        self._next_command = 0
        self.collector_control = _OperationalChannel()

    def _ack(self, command_kind: str, terminal_state: str) -> dict:
        self._next_command += 1
        return {
            "ok": True,
            "command_id": f"test-command-{self._next_command}",
            "command_kind": command_kind,
            "command_state": "completed",
            "terminal_state": terminal_state,
            "command_state_unknown": False,
        }

    def _attempt_ordinary_writer(self, label: str) -> None:
        outcome: list[str] = []

        def writer() -> None:
            try:
                project_service.create_project(f"BlockedDuring{label}")
            except sqlite3.OperationalError as exc:
                outcome.append(str(exc))

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        self.writer_outcomes.append((label, outcome[0] if outcome else "allowed"))

    def is_collection_running_for_maintenance(self) -> bool:
        return True

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        self.observed.append(
            ("quiesce", self.coordinator.phase, DATABASE_WRITE_GATE.phase())
        )
        return self._ack("maintenance_hold", "held")

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        self.observed.append(
            ("reset", self.coordinator.phase, DATABASE_WRITE_GATE.phase())
        )
        self._attempt_ordinary_writer("Reset")
        return self._ack("database_reset", "held")

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        self.observed.append(
            ("restore", self.coordinator.phase, DATABASE_WRITE_GATE.phase())
        )
        self._attempt_ordinary_writer("Release")
        return self._ack("maintenance_release", "operational")


def test_maintenance_gate_covers_operation_reset_restore_and_release(temp_db):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl(coordinator)
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    with coordinator.database_replacement("drain_contract"):
        control.observed.append(
            ("operation", coordinator.phase, DATABASE_WRITE_GATE.phase())
        )

    assert control.observed == [
        ("quiesce", MaintenancePhase.HOLD_REQUESTED, WriteGatePhase.OPEN),
        ("operation", MaintenancePhase.EXCLUSIVE, WriteGatePhase.EXCLUSIVE),
        ("reset", MaintenancePhase.RESETTING, WriteGatePhase.EXCLUSIVE),
        ("restore", MaintenancePhase.RELEASING, WriteGatePhase.EXCLUSIVE),
    ]
    assert control.writer_outcomes == [
        ("Reset", "database_maintenance_in_progress"),
        ("Release", "database_maintenance_in_progress"),
    ]
    assert coordinator.phase is MaintenancePhase.IDLE
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN
    assert DATABASE_WRITE_GATE.writes_blocked() is False


def test_snapshot_does_not_issue_replacement_reset(temp_db):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl(coordinator)
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    with coordinator.consistent_snapshot("snapshot_contract"):
        control.observed.append(
            ("operation", coordinator.phase, DATABASE_WRITE_GATE.phase())
        )

    assert [name for name, _phase, _gate in control.observed] == [
        "quiesce",
        "operation",
        "restore",
    ]


def test_draining_rejects_new_ordinary_writer(temp_db):
    outcome: list[str] = []

    def writer() -> None:
        try:
            project_service.create_project("RejectedDuringDrain")
        except sqlite3.OperationalError as exc:
            outcome.append(str(exc))

    with DATABASE_WRITE_GATE.draining():
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert outcome == ["database_maintenance_in_progress"]
    assert project_service.get_project_by_name("RejectedDuringDrain") is None
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN


def test_sqlite_barrier_waits_for_preexisting_writer_before_exclusive(temp_db):
    transaction_ready = threading.Event()
    allow_commit = threading.Event()
    committed = threading.Event()

    def existing_writer() -> None:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                ("321", "idle_threshold_seconds"),
            )
            transaction_ready.set()
            assert allow_commit.wait(timeout=5)
            conn.commit()
            committed.set()
        finally:
            conn.close()

    thread = threading.Thread(target=existing_writer, daemon=True)
    thread.start()
    assert transaction_ready.wait(timeout=5)

    with DATABASE_WRITE_GATE.draining() as lease:
        allow_commit.set()
        drain_existing_writers()
        assert committed.is_set()
        lease.promote()
        assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.EXCLUSIVE

    thread.join(timeout=5)
    assert not thread.is_alive()
    assert settings_service.get_int_setting("idle_threshold_seconds", 0) == 321
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN


def test_failed_reset_hands_exclusive_ownership_to_recovery_block(temp_db):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl(coordinator)
    control.reset_after_database_replacement = lambda timeout_seconds=5.0: {
        "ok": False,
        "command_id": "failed-reset",
        "command_kind": "database_reset",
        "command_state": "completed",
        "terminal_state": "held",
        "command_state_unknown": False,
    }
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    with pytest.raises(RuntimeError, match="collector_database_reset_not_acknowledged"):
        with coordinator.database_replacement("failure_contract"):
            pass

    status = coordinator.status()
    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert coordinator.blocked_reason == "failure_contract_restore"
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN
    assert DATABASE_WRITE_GATE.operation_active() is False
    assert DATABASE_WRITE_GATE.recovery_blocked() is True
    assert DATABASE_WRITE_GATE.writes_blocked() is True
    assert status.maintenance_in_progress is False
    assert status.recovery_blocked is True
    assert status.maintenance_restored is False
    assert settings_service.get_bool_setting("user_paused", False) is True
    assert settings_service.get_setting("collector_status", "") == "paused"


def test_secure_backup_exposes_no_second_maintenance_coordinator() -> None:
    root = Path(__file__).resolve().parents[1]
    backup = (root / "worktrace/services/secure_backup_service.py").read_text(
        encoding="utf-8"
    )
    services = root / "worktrace/services"

    assert "RuntimeMaintenanceCoordinator" not in backup
    assert "database_maintenance_service.consistent_snapshot" in backup
    assert "database_maintenance_service.database_replacement" in backup
    assert not (services / "runtime_snapshot_barrier.py").exists()


def test_drain_existing_writers_failure_runs_restore_or_fail_closed(
    temp_db, monkeypatch
):
    """Drain failure during DRAINING (before EXCLUSIVE) triggers outer-except restore.

    With ``exclusive_finalization_completed`` still False, the outer except runs
    ``_restore_after_failure``. The test double's restore succeeds, so the
    coordinator must return to IDLE and leave the write gate OPEN/unblocked.
    """
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl(coordinator)
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    monkeypatch.setattr(
        database_maintenance_service,
        "drain_existing_writers",
        lambda: (_ for _ in ()).throw(RuntimeError("drain_failed")),
    )

    with pytest.raises(RuntimeError, match="drain_failed"):
        with coordinator.consistent_snapshot("drain_boundary"):
            pass

    assert coordinator.phase is MaintenancePhase.IDLE
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN
    assert DATABASE_WRITE_GATE.recovery_blocked() is False
    assert DATABASE_WRITE_GATE.operation_active() is False
    assert "restore" in [name for name, _, _ in control.observed]


def test_lease_promote_failure_runs_restore_or_fail_closed(
    temp_db, monkeypatch
):
    """Promote failure during DRAINING (before EXCLUSIVE) triggers outer-except restore.

    Same contract as the drain-failure case: ``exclusive_finalization_completed``
    is False, so the outer except runs ``_restore_after_failure``. Successful
    restore returns the coordinator to IDLE with the write gate OPEN/unblocked.
    """
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl(coordinator)
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    monkeypatch.setattr(
        ProcessDatabaseWriteGate,
        "promote_to_exclusive",
        lambda self, owner_thread_id: (_ for _ in ()).throw(
            sqlite3.OperationalError("promote_failed")
        ),
    )

    with pytest.raises(sqlite3.OperationalError, match="promote_failed"):
        with coordinator.consistent_snapshot("promote_boundary"):
            pass

    assert coordinator.phase is MaintenancePhase.IDLE
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN
    assert DATABASE_WRITE_GATE.recovery_blocked() is False
    assert DATABASE_WRITE_GATE.operation_active() is False
    assert "restore" in [name for name, _, _ in control.observed]


def test_drain_failure_with_restore_failure_enters_failed_closed(
    temp_db, monkeypatch
):
    """Drain failure during DRAINING + restore failure → FAILED_CLOSED (``_operation``).

    The body never returned and no durable replacement was committed, so the
    fail-closed command suffix is ``operation`` (not ``restore``). The original
    drain exception is re-raised after entering FAILED_CLOSED.
    """
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl(coordinator)
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    monkeypatch.setattr(
        database_maintenance_service,
        "drain_existing_writers",
        lambda: (_ for _ in ()).throw(RuntimeError("drain_failed")),
    )
    control.restore_after_maintenance = lambda state, timeout_seconds=5.0: (
        _ for _ in ()
    ).throw(RuntimeError("restore_failed"))

    with pytest.raises(RuntimeError, match="drain_failed"):
        with coordinator.consistent_snapshot("drain_restore_failure"):
            pass

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert coordinator.blocked_reason == "drain_restore_failure_operation"
    assert DATABASE_WRITE_GATE.recovery_blocked() is True
    assert DATABASE_WRITE_GATE.writes_blocked() is True
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN
    assert DATABASE_WRITE_GATE.operation_active() is False


def test_promote_failure_with_restore_failure_enters_failed_closed(
    temp_db, monkeypatch
):
    """Promote failure during DRAINING + restore failure → FAILED_CLOSED (``_operation``).

    Same contract as the drain+restore double failure: the body never reached
    EXCLUSIVE, so ``exclusive_finalization_completed`` is False and the outer
    except runs ``_restore_after_failure``. Restore failure forces
    ``_enter_fail_closed`` with the ``_operation`` suffix.
    """
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl(coordinator)
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    monkeypatch.setattr(
        ProcessDatabaseWriteGate,
        "promote_to_exclusive",
        lambda self, owner_thread_id: (_ for _ in ()).throw(
            sqlite3.OperationalError("promote_failed")
        ),
    )
    control.restore_after_maintenance = lambda state, timeout_seconds=5.0: (
        _ for _ in ()
    ).throw(RuntimeError("restore_failed"))

    with pytest.raises(sqlite3.OperationalError, match="promote_failed"):
        with coordinator.consistent_snapshot("promote_restore_failure"):
            pass

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert coordinator.blocked_reason == "promote_restore_failure_operation"
    assert DATABASE_WRITE_GATE.recovery_blocked() is True
    assert DATABASE_WRITE_GATE.writes_blocked() is True
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN
    assert DATABASE_WRITE_GATE.operation_active() is False
