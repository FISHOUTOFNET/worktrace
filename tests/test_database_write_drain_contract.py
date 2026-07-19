from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from worktrace.db import get_connection
from worktrace.services import project_service, settings_service
from worktrace.services.database_maintenance_barrier import drain_existing_writers
from worktrace.services.database_maintenance_service import (
    MaintenancePhase,
    RuntimeMaintenanceCoordinator,
)
from worktrace.write_gate import DATABASE_WRITE_GATE, WriteGatePhase

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


class _RuntimeControl:
    def __init__(self, coordinator: RuntimeMaintenanceCoordinator) -> None:
        self.coordinator = coordinator
        self.observed: list[tuple[str, MaintenancePhase, WriteGatePhase]] = []

    def is_collection_running_for_maintenance(self) -> bool:
        return True

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        self.observed.append(
            ("quiesce", self.coordinator.phase, DATABASE_WRITE_GATE.phase())
        )
        return {"ok": True, "quiesce_pending": False}

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        self.observed.append(
            ("reset", self.coordinator.phase, DATABASE_WRITE_GATE.phase())
        )
        return {"ok": True, "reset_pending": False}

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        self.observed.append(
            ("restore", self.coordinator.phase, DATABASE_WRITE_GATE.phase())
        )
        return {"ok": True, "restore_pending": False}


def test_maintenance_quiesces_before_draining_and_resets_after_exclusive(temp_db):
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
        ("quiesce", MaintenancePhase.QUIESCING, WriteGatePhase.OPEN),
        ("operation", MaintenancePhase.EXCLUSIVE, WriteGatePhase.EXCLUSIVE),
        ("reset", MaintenancePhase.RESTORING, WriteGatePhase.OPEN),
        ("restore", MaintenancePhase.RESTORING, WriteGatePhase.OPEN),
    ]
    assert coordinator.phase is MaintenancePhase.IDLE
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN


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

    assert outcome == ["secure_import_in_progress"]
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


def test_failed_reset_releases_gate_and_fails_closed(temp_db):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _RuntimeControl(coordinator)
    control.reset_after_database_replacement = lambda timeout_seconds=5.0: {
        "ok": False,
        "reset_pending": False,
    }
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    with pytest.raises(RuntimeError, match="collector_reset_not_acknowledged"):
        with coordinator.database_replacement("failure_contract"):
            pass

    assert coordinator.phase is MaintenancePhase.IDLE
    assert coordinator.active() is False
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN
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
