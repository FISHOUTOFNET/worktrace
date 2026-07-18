from __future__ import annotations

import sqlite3
import threading

import pytest

from worktrace.db import get_connection
from worktrace.services import project_service, settings_service
from worktrace.services.database_maintenance_barrier import drain_existing_writers
from worktrace.services.database_maintenance_service import (
    DatabaseMaintenanceCoordinator,
    MaintenancePhase,
)
from worktrace.write_gate import DATABASE_WRITE_GATE, WriteGatePhase

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


def test_maintenance_enters_draining_before_pause_and_exclusive_before_operation(
    temp_db,
):
    coordinator = DatabaseMaintenanceCoordinator()
    observed: list[tuple[str, MaintenancePhase, WriteGatePhase]] = []

    def pause(timeout_seconds=5.0):
        observed.append(("pause", coordinator.phase, DATABASE_WRITE_GATE.phase()))
        return {"ok": True, "pause_pending": False}

    def reset(timeout_seconds=5.0):
        observed.append(("reset", coordinator.phase, DATABASE_WRITE_GATE.phase()))
        return {"ok": True, "reset_pending": False}

    coordinator.register_pause_handler(pause)
    coordinator.register_reset_handler(reset)

    with coordinator.acquire(reason="drain_contract") as state:
        observed.append(
            ("operation", coordinator.phase, DATABASE_WRITE_GATE.phase())
        )
        state.mark_succeeded()

    assert observed == [
        ("pause", MaintenancePhase.DRAINING, WriteGatePhase.DRAINING),
        ("reset", MaintenancePhase.DRAINING, WriteGatePhase.DRAINING),
        ("operation", MaintenancePhase.EXCLUSIVE, WriteGatePhase.EXCLUSIVE),
    ]
    assert coordinator.phase is MaintenancePhase.IDLE
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN


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


def test_failed_reset_releases_coordinator_and_process_gate(temp_db):
    coordinator = DatabaseMaintenanceCoordinator()
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    coordinator.register_pause_handler(
        lambda timeout_seconds=5.0: {"ok": True, "pause_pending": False}
    )
    coordinator.register_reset_handler(
        lambda timeout_seconds=5.0: {"ok": False, "reset_pending": False}
    )

    with pytest.raises(RuntimeError, match="collector_reset_not_acknowledged"):
        with coordinator.acquire(reason="failure_contract"):
            pytest.fail("exclusive operation must not begin")

    assert coordinator.phase is MaintenancePhase.IDLE
    assert coordinator.active() is False
    assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.OPEN
    assert settings_service.get_bool_setting("user_paused", True) is False
    assert settings_service.get_setting("collector_status", "") == "running"
