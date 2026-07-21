from __future__ import annotations

import pytest

from worktrace.services import (
    database_maintenance_service,
    maintenance_recovery_latch_repository,
    settings_service,
)
from worktrace.services.database_maintenance_service import (
    CollectorCommandNotAcknowledgedError,
    MaintenancePhase,
    RuntimeMaintenanceCoordinator,
)
from worktrace.write_gate import DATABASE_WRITE_GATE

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


class _OperationalHoldState:
    value = "operational"


class _UnknownHoldControl:
    def __init__(self) -> None:
        self.collector_control = self
        self.hold_state = _OperationalHoldState()
        self.hold_calls = 0

    def query_command(self, command_id: str):
        return None

    def is_collection_running_for_maintenance(self) -> bool:
        return True

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        self.hold_calls += 1
        return {
            "ok": False,
            "command_id": "unknown-hold",
            "command_kind": "maintenance_hold",
            "command_state": "unknown",
            "command_state_unknown": True,
            "terminal_state": "sealing",
        }

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        raise AssertionError("snapshot must not reset replacement state")

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        raise AssertionError("unknown hold must not release")


def _clear_block(coordinator: RuntimeMaintenanceCoordinator) -> None:
    latch = maintenance_recovery_latch_repository.read_latch()
    if latch.epoch:
        with DATABASE_WRITE_GATE._maintenance_recovery_write_scope():
            maintenance_recovery_latch_repository.clear_latch(
                expected_epoch=latch.epoch
            )
    DATABASE_WRITE_GATE._clear_recovery_block()
    coordinator._set_phase(MaintenancePhase.IDLE)


def test_snapshot_unknown_hold_keeps_prearmed_seal_when_mirror_write_fails(
    temp_db,
    monkeypatch,
):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _UnknownHoldControl()
    coordinator.register_runtime_control(control)
    settings_service.set_settings(
        {"user_paused": "false", "collector_status": "running"}
    )

    def fail_mirror(_reason: str, *, expected_epoch: str | None = None):
        assert expected_epoch
        raise RuntimeError("mirror_unavailable")

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "persist_fail_closed",
        fail_mirror,
    )

    try:
        with pytest.raises(
            CollectorCommandNotAcknowledgedError,
            match="collector_maintenance_hold_not_acknowledged",
        ):
            with coordinator.consistent_snapshot("snapshot_unknown_hold"):
                pytest.fail("snapshot body must not run")

        latch = maintenance_recovery_latch_repository.read_latch()
        assert latch.blocked is True
        assert latch.state == "armed"
        assert latch.epoch
        assert control.hold_calls == 1
        assert coordinator.recovery_blocked() is True

        restarted = RuntimeMaintenanceCoordinator()
        assert restarted.hydrate_fail_closed_from_durable() is True
        assert restarted.recovery_blocked() is True
    finally:
        _clear_block(coordinator)


def test_recovery_seal_arm_failure_aborts_before_collector_hold(
    temp_db,
    monkeypatch,
):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _UnknownHoldControl()
    coordinator.register_runtime_control(control)
    settings_service.set_settings(
        {"user_paused": "false", "collector_status": "running"}
    )

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "arm_recovery",
        lambda _reason: (_ for _ in ()).throw(RuntimeError("seal_create_failed")),
    )

    with pytest.raises(RuntimeError, match="seal_create_failed"):
        with coordinator.consistent_snapshot("snapshot_arm_failure"):
            pytest.fail("snapshot body must not run")

    assert control.hold_calls == 0
    assert coordinator.phase is MaintenancePhase.IDLE
    assert coordinator.recovery_blocked() is False
    assert DATABASE_WRITE_GATE.writes_blocked() is False
