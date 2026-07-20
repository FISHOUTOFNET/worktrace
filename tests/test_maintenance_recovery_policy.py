from __future__ import annotations

import pytest

from worktrace.services.database_maintenance_service import (
    MaintenancePhase,
    MaintenanceRecoveryError,
    RuntimeMaintenanceCoordinator,
)
from worktrace.services.settings_service import get_bool_setting, set_settings
from worktrace.write_gate import DATABASE_WRITE_GATE

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


class _HoldState:
    def __init__(self, value: str) -> None:
        self.value = value


class _CollectorControl:
    def __init__(self, value: str = "operational") -> None:
        self.hold_state = _HoldState(value)


class _StoppedRuntimeControl:
    def __init__(self, hold_state: str = "operational") -> None:
        self.collector_control = _CollectorControl(hold_state)

    def is_collection_running_for_maintenance(self) -> bool:
        return False


def _blocked_coordinator(control: _StoppedRuntimeControl) -> RuntimeMaintenanceCoordinator:
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(control)
    coordinator._latch_fail_closed("test_failed_closed")
    set_settings(
        {
            "maintenance_fail_closed": "true",
            "maintenance_fail_closed_reason": "test_failed_closed",
            "user_paused": "true",
            "collector_status": "paused",
        }
    )
    return coordinator


def test_stopped_collector_can_recover_when_runtime_boundary_is_operational(temp_db) -> None:
    coordinator = _blocked_coordinator(_StoppedRuntimeControl())

    coordinator.recover_fail_closed()

    assert coordinator.phase is MaintenancePhase.IDLE
    assert coordinator.blocked_reason is None
    assert get_bool_setting("maintenance_fail_closed", True) is False
    assert get_bool_setting("user_paused", False) is True


def test_non_operational_hold_state_remains_fail_closed(temp_db) -> None:
    coordinator = _blocked_coordinator(_StoppedRuntimeControl("held"))

    with pytest.raises(MaintenanceRecoveryError, match="maintenance_recovery_not_verified"):
        coordinator.recover_fail_closed()

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert coordinator.blocked_reason == "test_failed_closed"


def test_active_write_gate_prevents_fail_closed_recovery(temp_db) -> None:
    coordinator = _blocked_coordinator(_StoppedRuntimeControl())

    with DATABASE_WRITE_GATE.draining():
        with pytest.raises(
            MaintenanceRecoveryError,
            match="maintenance_recovery_not_verified",
        ):
            coordinator.recover_fail_closed()

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
