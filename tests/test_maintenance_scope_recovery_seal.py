from __future__ import annotations

import pytest

from worktrace.services import (
    database_maintenance_service,
    maintenance_recovery_latch_repository,
    settings_service,
)
from worktrace.services.database_maintenance_service import (
    MaintenanceIntent,
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


def test_snapshot_does_not_pre_arm_recovery_seal(temp_db, monkeypatch):
    """Ordinary read-only snapshots must not arm a cross-restart recovery seal.

    A consistent snapshot does not replace the database and creates no
    irreversible durable effect; the old collector thread naturally disappears
    on process restart. Only database replacement and sensitive staging
    require durable recovery evidence.
    """

    coordinator = RuntimeMaintenanceCoordinator()
    control = _UnknownHoldControl()
    coordinator.register_runtime_control(control)
    settings_service.set_settings(
        {"user_paused": "false", "collector_status": "running"}
    )

    arm_calls: list[str] = []
    original_arm = maintenance_recovery_latch_repository.arm_recovery

    def tracking_arm(reason: str):
        arm_calls.append(reason)
        return original_arm(reason)

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "arm_recovery",
        tracking_arm,
    )

    try:
        with pytest.raises(
            database_maintenance_service.CollectorCommandNotAcknowledgedError,
            match="collector_maintenance_hold_not_acknowledged",
        ):
            with coordinator.consistent_snapshot("snapshot_no_prearm"):
                pytest.fail("snapshot body must not run")

        # Snapshots must not pre-arm a recovery seal before hold.
        assert arm_calls == []
        assert control.hold_calls == 1
        # Unknown hold still fails safely within the current process.
        assert coordinator.recovery_blocked() is True
        assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    finally:
        _clear_block(coordinator)


def test_database_replacement_pre_arms_recovery_seal(temp_db, monkeypatch):
    """Database replacement must arm the recovery seal before requesting hold."""

    coordinator = RuntimeMaintenanceCoordinator()
    control = _UnknownHoldControl()
    coordinator.register_runtime_control(control)
    settings_service.set_settings(
        {"user_paused": "false", "collector_status": "running"}
    )

    arm_calls: list[str] = []
    original_arm = maintenance_recovery_latch_repository.arm_recovery

    def tracking_arm(reason: str):
        arm_calls.append(reason)
        return original_arm(reason)

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "arm_recovery",
        tracking_arm,
    )

    try:
        with pytest.raises(
            database_maintenance_service.CollectorCommandNotAcknowledgedError,
            match="collector_maintenance_hold_not_acknowledged",
        ):
            with coordinator.database_replacement("replacement_prearm"):
                pytest.fail("replacement body must not run")

        assert arm_calls == ["replacement_prearm"]
        assert control.hold_calls == 1
        assert coordinator.recovery_blocked() is True
        assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    finally:
        _clear_block(coordinator)
