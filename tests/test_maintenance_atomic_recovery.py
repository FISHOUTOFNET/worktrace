from __future__ import annotations

import sqlite3

import pytest

from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime as runtime_module
from worktrace.runtime.app_runtime import AppRuntime, RuntimePhase
from worktrace.services import (
    database_maintenance_service,
    maintenance_recovery_latch_repository,
    settings_service,
)
from worktrace.services.database_maintenance_service import (
    MaintenancePhase,
    MaintenanceRecoveryError,
    RuntimeMaintenanceCoordinator,
)
from worktrace.write_gate import DATABASE_WRITE_GATE, ProcessDatabaseWriteGate

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


def _ack(kind: str, terminal_state: str) -> dict[str, object]:
    return {
        "ok": True,
        "command_id": f"{kind}-ack",
        "command_kind": kind,
        "command_state": "completed",
        "command_state_unknown": False,
        "terminal_state": terminal_state,
    }


class _OperationalHoldState:
    value = "operational"


class _OperationalChannel:
    hold_state = _OperationalHoldState()

    def query_command(self, command_id: str):
        return None


class _Control:
    def __init__(self, *, running: bool = False, reset_ok: bool = True) -> None:
        self.running = running
        self.reset_ok = reset_ok
        self.collector_control = _OperationalChannel()

    def is_collection_running_for_maintenance(self) -> bool:
        return self.running

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        return _ack("maintenance_hold", "held")

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        if self.reset_ok:
            return _ack("database_reset", "held")
        return {
            "ok": False,
            "command_id": "database-reset-failed",
            "command_kind": "database_reset",
            "command_state": "completed",
            "command_state_unknown": False,
            "terminal_state": "held",
        }

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        return _ack("maintenance_release", "operational")


def _persist_blocked_latch(reason: str = "durable_failure") -> None:
    settings_service.set_settings(
        {
            "maintenance_fail_closed": "true",
            "maintenance_fail_closed_reason": reason,
            "user_paused": "true",
            "collector_status": "paused",
        }
    )


def test_recovery_clear_failure_keeps_process_and_durable_blocks(
    temp_db,
    monkeypatch,
):
    _persist_blocked_latch()
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control())
    assert coordinator.hydrate_fail_closed_from_durable() is True

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "clear_latch",
        lambda: (_ for _ in ()).throw(RuntimeError("durable_clear_failed")),
    )

    with pytest.raises(RuntimeError, match="durable_clear_failed"):
        coordinator.recover_fail_closed()

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert DATABASE_WRITE_GATE.recovery_blocked() is True
    assert settings_service.get_bool_setting("maintenance_fail_closed", False) is True


def test_superseded_recovery_repersists_latch_and_keeps_process_block(
    temp_db,
    monkeypatch,
):
    _persist_blocked_latch()
    coordinator = RuntimeMaintenanceCoordinator()
    original_control = _Control()
    replacement_control = _Control()
    coordinator.register_runtime_control(original_control)
    assert coordinator.hydrate_fail_closed_from_durable() is True

    original_clear = maintenance_recovery_latch_repository.clear_latch

    def clear_then_replace_control() -> None:
        original_clear()
        coordinator.register_runtime_control(replacement_control)

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "clear_latch",
        clear_then_replace_control,
    )

    with pytest.raises(
        MaintenanceRecoveryError,
        match="maintenance_recovery_superseded",
    ):
        coordinator.recover_fail_closed()

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert coordinator.blocked_reason == "maintenance_recovery_superseded"
    assert settings_service.get_bool_setting("maintenance_fail_closed", False) is True
    assert (
        settings_service.get_setting("maintenance_fail_closed_reason", "")
        == "maintenance_recovery_superseded"
    )


def test_successful_recovery_clears_durable_before_process_block(temp_db):
    _persist_blocked_latch()
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control())
    assert coordinator.hydrate_fail_closed_from_durable() is True

    coordinator.recover_fail_closed()

    assert coordinator.phase is MaintenancePhase.IDLE
    assert DATABASE_WRITE_GATE.recovery_blocked() is False
    assert settings_service.get_bool_setting("maintenance_fail_closed", True) is False
    assert settings_service.get_setting("maintenance_fail_closed_reason", "x") == ""


def test_fail_closed_persistence_failure_does_not_open_process_gate(
    temp_db,
    monkeypatch,
):
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control(running=True, reset_ok=False))
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "persist_fail_closed",
        lambda reason: (_ for _ in ()).throw(RuntimeError("persist_failed")),
    )

    with pytest.raises(RuntimeError, match="collector_database_reset_not_acknowledged"):
        with coordinator.database_replacement("persist_failure"):
            pass

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert DATABASE_WRITE_GATE.operation_active() is False
    assert DATABASE_WRITE_GATE.recovery_blocked() is True
    assert DATABASE_WRITE_GATE.writes_blocked() is True


def test_recovery_write_scope_accepts_latch_upserts_and_rejects_escape_sql():
    gate = ProcessDatabaseWriteGate()
    gate._set_recovery_block("test")

    with gate._maintenance_recovery_write_scope():
        gate.require_current_thread_allowed("BEGIN IMMEDIATE")
        gate.require_current_thread_allowed(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES ('maintenance_fail_closed', 'true', '2026-07-20 00:00:00')
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """
        )
        gate.require_current_thread_allowed(
            "UPDATE data_generation_state SET value = 2"
        )
        with pytest.raises(
            sqlite3.OperationalError,
            match="database_maintenance_recovery_required",
        ):
            gate.require_current_thread_allowed(
                "INSERT INTO project(name) VALUES ('forbidden')"
            )
        with pytest.raises(
            sqlite3.OperationalError,
            match="database_maintenance_recovery_required",
        ):
            gate.require_current_thread_allowed(
                "UPDATE settings SET value = 'x'; "
                "INSERT INTO project(name) VALUES ('forbidden')"
            )


def test_startup_hydrates_durable_latch_before_recovery_or_worker_start(
    temp_db,
    tmp_path,
    monkeypatch,
):
    _persist_blocked_latch("startup_blocked")
    recovery_calls: list[str] = []
    release_calls: list[str] = []
    monkeypatch.setattr(runtime_module, "acquire_single_instance", lambda: True)
    monkeypatch.setattr(
        runtime_module,
        "release_single_instance",
        lambda: release_calls.append("released"),
    )
    monkeypatch.setattr(
        runtime_module.recovery_service,
        "recover_unclosed_records",
        lambda: recovery_calls.append("recovery"),
    )
    paths = type(
        "Paths",
        (),
        {"db_path": str(temp_db), "log_path": str(tmp_path / "runtime.log")},
    )()
    runtime = AppRuntime(paths, adapter=FakeAdapter())

    assert runtime.initialize() is True
    assert recovery_calls == []
    assert runtime.phase is RuntimePhase.RECOVERABLE_FAILURE
    assert runtime._worker_handles == {}
    assert runtime.start_collector() == {
        "ok": False,
        "error": "database_maintenance_recovery_required",
    }
    worker_report = runtime.start_background_workers()
    assert worker_report.ready is False
    assert worker_report.started_any is False
    assert worker_report.error_code == "database_maintenance_recovery_required"

    runtime.shutdown()

    assert runtime.phase is RuntimePhase.STOPPED
    assert release_calls == ["released"]
    assert settings_service.get_bool_setting("maintenance_fail_closed", False) is True
