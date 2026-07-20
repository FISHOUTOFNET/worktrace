from __future__ import annotations

import pytest

from worktrace.services import database_maintenance_service, settings_service
from worktrace.services.database_maintenance_service import RuntimeMaintenanceCoordinator

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


def test_lost_hold_response_is_recovered_from_terminal_command_state(
    temp_db,
    monkeypatch,
):
    coordinator = RuntimeMaintenanceCoordinator()
    control = _Control(_ack("hold-1", "maintenance_hold", "held"))
    coordinator.register_runtime_control(control)
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )

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
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )

    with pytest.raises(RuntimeError, match="collector_maintenance_hold_not_acknowledged"):
        with coordinator.consistent_snapshot("unknown_response"):
            pytest.fail("exclusive operation must not start")

    assert control.calls == ["hold"]
    assert settings_service.get_bool_setting("user_paused", False) is True
    assert settings_service.get_setting("collector_status") == "paused"
