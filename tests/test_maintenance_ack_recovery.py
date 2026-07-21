from __future__ import annotations

import pytest

from worktrace.services import database_maintenance_service, settings_service
from worktrace.services.database_maintenance_service import (
    MaintenancePhase,
    RuntimeMaintenanceCoordinator,
)
from worktrace.write_gate import DATABASE_WRITE_GATE, WriteGatePhase

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _ack(command_id: str, kind: str, terminal: str) -> dict[str, object]:
    return {
        "ok": True,
        "command_id": command_id,
        "command_kind": kind,
        "command_state": "completed",
        "command_state_unknown": False,
        "terminal_state": terminal,
    }


class _Channel:
    def __init__(self, completed: dict[str, object] | None) -> None:
        self.completed = completed
        self.queries: list[str] = []

    def query_command(self, command_id: str):
        self.queries.append(command_id)
        return self.completed


class _Control:
    def __init__(self, completed: dict[str, object] | None) -> None:
        self.collector_control = _Channel(completed)
        self.calls: list[str] = []

    def is_collection_running_for_maintenance(self) -> bool:
        return True

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        self.calls.append("hold")
        return {
            "ok": False,
            "command_id": "hold-1",
            "command_kind": "maintenance_hold",
            "command_state": "unknown",
            "command_state_unknown": True,
            "terminal_state": "sealing",
        }

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        self.calls.append("release")
        return _ack("release-1", "maintenance_release", "operational")


class _OrderedControl:
    def __init__(
        self,
        events: list[str],
        *,
        running: bool = True,
        release_mode: str = "success",
    ) -> None:
        self.events = events
        self.running = running
        self.release_mode = release_mode
        self.collector_control = _Channel(None)
        self.restored_states: list[object] = []

    def is_collection_running_for_maintenance(self) -> bool:
        return self.running

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        self.events.append("maintenance_hold")
        return _ack("hold-ordered", "maintenance_hold", "held")

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        self.events.append("database_reset")
        return _ack("reset-ordered", "database_reset", "held")

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        self.events.append("maintenance_release")
        self.restored_states.append(state)
        assert DATABASE_WRITE_GATE.phase() is WriteGatePhase.EXCLUSIVE
        if self.release_mode == "raise":
            raise RuntimeError("release failed")
        if self.release_mode == "unknown":
            return {
                "ok": False,
                "command_id": "release-unknown",
                "command_kind": "maintenance_release",
                "command_state": "unknown",
                "command_state_unknown": True,
                "terminal_state": "releasing",
            }
        return _ack("release-ordered", "maintenance_release", "operational")


def _prepare_runtime_state(monkeypatch, *, paused: bool = False, privacy: bool = True):
    settings_service.set_setting("user_paused", "true" if paused else "false")
    settings_service.set_setting(
        "collector_status",
        "paused" if paused else "running",
    )
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: privacy,
    )


def _clear_test_fail_closed(coordinator: RuntimeMaintenanceCoordinator) -> None:
    if DATABASE_WRITE_GATE.recovery_blocked():
        with DATABASE_WRITE_GATE._maintenance_recovery_write_scope():
            database_maintenance_service.maintenance_recovery_latch_repository.clear_latch()
        DATABASE_WRITE_GATE._clear_recovery_block()
    coordinator._set_phase(MaintenancePhase.IDLE)


def test_lost_hold_response_is_recovered_from_terminal_command_state(
    temp_db,
    monkeypatch,
):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _Control(_ack("hold-1", "maintenance_hold", "held"))
    coordinator.register_runtime_control(control)
    _prepare_runtime_state(monkeypatch)

    with coordinator.consistent_snapshot("lost_response"):
        control.calls.append("operation")

    assert control.calls == ["hold", "operation", "release"]
    assert control.collector_control.queries == ["hold-1"]


def test_unknown_hold_without_confirmed_terminal_state_fails_closed(
    temp_db,
    monkeypatch,
):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _Control(None)
    coordinator.register_runtime_control(control)
    _prepare_runtime_state(monkeypatch)

    try:
        with pytest.raises(RuntimeError, match="collector_maintenance_hold_not_acknowledged"):
            with coordinator.consistent_snapshot("unknown_response"):
                pytest.fail("exclusive operation must not start")

        assert control.calls == ["hold"]
        assert settings_service.get_bool_setting("user_paused", False) is True
        assert settings_service.get_setting("collector_status") == "paused"
    finally:
        _clear_test_fail_closed(coordinator)


def test_precommit_failure_restores_durable_before_release_and_scope_exit(
    temp_db,
    monkeypatch,
):
    events: list[str] = []
    coordinator = RuntimeMaintenanceCoordinator()
    control = _OrderedControl(events)
    coordinator.register_runtime_control(control)
    _prepare_runtime_state(monkeypatch)
    original_restore = coordinator._restore_durable_state

    def recording_restore(state):
        events.append("durable_restore")
        original_restore(state)

    monkeypatch.setattr(coordinator, "_restore_durable_state", recording_restore)

    with pytest.raises(RuntimeError, match="live operation failed"):
        try:
            with coordinator.consistent_snapshot("precommit_failure"):
                events.append("live_operation")
                raise RuntimeError("live operation failed")
        finally:
            events.append("exclusive_scope_exit")

    assert events.index("durable_restore") < events.index("maintenance_release")
    assert events.index("maintenance_release") < events.index("exclusive_scope_exit")
    assert coordinator.phase is MaintenancePhase.IDLE
    assert coordinator.recovery_blocked() is False


def test_durable_restore_failure_never_releases_collector(
    temp_db,
    monkeypatch,
):
    events: list[str] = []
    coordinator = RuntimeMaintenanceCoordinator()
    control = _OrderedControl(events)
    coordinator.register_runtime_control(control)
    _prepare_runtime_state(monkeypatch)

    def fail_durable_restore(_state):
        events.append("durable_restore")
        raise RuntimeError("durable restore failed")

    monkeypatch.setattr(coordinator, "_restore_durable_state", fail_durable_restore)

    try:
        with pytest.raises(RuntimeError, match="live operation failed"):
            with coordinator.consistent_snapshot("durable_restore_failure"):
                events.append("live_operation")
                raise RuntimeError("live operation failed")

        assert "maintenance_release" not in events
        assert coordinator.recovery_blocked() is True
        assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    finally:
        _clear_test_fail_closed(coordinator)


def test_release_failure_after_durable_restore_fails_closed(
    temp_db,
    monkeypatch,
):
    events: list[str] = []
    coordinator = RuntimeMaintenanceCoordinator()
    control = _OrderedControl(events, release_mode="raise")
    coordinator.register_runtime_control(control)
    _prepare_runtime_state(monkeypatch)
    original_restore = coordinator._restore_durable_state

    def recording_restore(state):
        events.append("durable_restore")
        original_restore(state)

    monkeypatch.setattr(coordinator, "_restore_durable_state", recording_restore)

    try:
        with pytest.raises(RuntimeError, match="release failed"):
            with coordinator.consistent_snapshot("release_failure"):
                events.append("live_operation")

        assert events.index("durable_restore") < events.index("maintenance_release")
        assert coordinator.recovery_blocked() is True
        assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    finally:
        _clear_test_fail_closed(coordinator)


def test_unknown_release_ack_is_not_optimistically_recovered(
    temp_db,
    monkeypatch,
):
    events: list[str] = []
    coordinator = RuntimeMaintenanceCoordinator()
    control = _OrderedControl(events, release_mode="unknown")
    coordinator.register_runtime_control(control)
    _prepare_runtime_state(monkeypatch)

    try:
        with pytest.raises(
            database_maintenance_service.CollectorCommandNotAcknowledgedError,
            match="collector_maintenance_release_not_acknowledged",
        ):
            with coordinator.consistent_snapshot("unknown_release"):
                events.append("live_operation")

        assert coordinator.recovery_blocked() is True
        assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    finally:
        _clear_test_fail_closed(coordinator)


def test_originally_stopped_collector_is_not_started_by_restoration(
    temp_db,
    monkeypatch,
):
    events: list[str] = []
    coordinator = RuntimeMaintenanceCoordinator()
    control = _OrderedControl(events, running=False)
    coordinator.register_runtime_control(control)
    _prepare_runtime_state(monkeypatch)

    with coordinator.consistent_snapshot("stopped_collector"):
        events.append("live_operation")

    assert events == ["live_operation"]
    assert control.restored_states == []
    assert settings_service.get_setting("collector_status") == "stopped"
    assert coordinator.phase is MaintenancePhase.IDLE


def test_preexisting_pause_and_privacy_gate_are_preserved_before_release(
    temp_db,
    monkeypatch,
):
    events: list[str] = []
    coordinator = RuntimeMaintenanceCoordinator()
    control = _OrderedControl(events)
    coordinator.register_runtime_control(control)
    _prepare_runtime_state(monkeypatch, paused=True, privacy=False)

    with coordinator.consistent_snapshot("paused_privacy"):
        events.append("live_operation")

    state = control.restored_states[-1]
    assert state.user_paused is True
    assert state.privacy_notice_accepted is False
    assert settings_service.get_bool_setting("user_paused", False) is True
    assert settings_service.get_setting("collector_status") == "paused"
