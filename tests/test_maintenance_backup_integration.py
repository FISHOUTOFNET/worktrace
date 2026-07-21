from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from worktrace import db
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.security.backup_format import decrypt_encrypted_backup
from worktrace.services import (
    database_maintenance_service,
    runtime_activity_state_service,
    secure_backup_service,
    settings_service,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]

PASSPHRASE = "maintenance-integration-passphrase"


class _OperationalHoldState:
    value = "operational"


def _payload(status: str) -> dict[str, object]:
    return {
        "status": status,
        "app_name": "Word" if status == "normal" else "System",
        "process_name": "winword.exe" if status == "normal" else "system",
        "window_title": "Matter.docx" if status == "normal" else status,
        "file_path_hint": "C:\\Matter\\Matter.docx" if status == "normal" else None,
    }


def _active_machine(status: str, start_time: str) -> CollectorStateMachine:
    machine = CollectorStateMachine()
    payload = _payload(status)
    signature = machine.resolver.signature_for_payload(payload)
    machine.recorder.observe(payload, signature, start_time)
    machine.state = "recording" if status == "normal" else status
    machine.active_signature = signature
    assert machine.recorder.persisted_activity_id is not None
    return machine


@dataclass
class _MachineRuntimeControl:
    machine: CollectorStateMachine
    quiesce_at: str
    resume_at: str
    restore_observed: bool = False
    reset_observed: bool = False
    _next_command: int = field(default=0, init=False)
    collector_control: object = field(init=False)
    hold_state: object = field(init=False)

    def __post_init__(self) -> None:
        self.collector_control = self
        self.hold_state = _OperationalHoldState()

    def query_command(self, command_id: str):
        return None

    def _ack(self, command_kind: str, terminal_state: str) -> dict:
        self._next_command += 1
        return {
            "ok": True,
            "command_id": f"machine-command-{self._next_command}",
            "command_kind": command_kind,
            "command_state": "completed",
            "terminal_state": terminal_state,
            "command_state_unknown": False,
        }

    def is_collection_running_for_maintenance(self) -> bool:
        return True

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        self.machine.quiesce_for_maintenance(self.quiesce_at)
        return self._ack("maintenance_hold", "held")

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        self.reset_observed = True
        self.machine.reset_runtime_state("database_replacement")
        return self._ack("database_reset", "held")

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        self.restore_observed = True
        if (
            state.collector_running
            and state.privacy_notice_accepted
            and not state.user_paused
        ):
            self.machine.transition_to(
                "recording",
                ActiveWindow(
                    "Word",
                    "winword.exe",
                    "Matter.docx",
                    "C:\\Matter\\Matter.docx",
                ),
                at_time=self.resume_at,
            )
        return self._ack("maintenance_release", "operational")


def test_direct_backup_export_seals_and_resumes_without_maintenance_boundary(
    temp_db,
    tmp_path,
    monkeypatch,
):
    machine = _active_machine("normal", "2026-07-19 10:00:00")
    old_activity_id = int(machine.recorder.persisted_activity_id or 0)
    control = _MachineRuntimeControl(
        machine,
        quiesce_at="2026-07-19 10:02:00",
        resume_at="2026-07-19 10:02:01",
    )
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    database_maintenance_service.register_runtime_control(control)
    out = tmp_path / "direct-export.wtbackup"
    try:
        secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
    finally:
        database_maintenance_service.clear_runtime_control(control)

    payload = json.loads(decrypt_encrypted_backup(out.read_bytes(), PASSPHRASE))
    exported = next(
        row for row in payload["tables"]["activity_log"] if row["id"] == old_activity_id
    )
    assert exported["end_time"] == "2026-07-19 10:02:00"
    assert exported["duration_seconds"] == 120

    with db.get_connection() as conn:
        durable = conn.execute(
            "SELECT end_time, duration_seconds FROM activity_log WHERE id = ?",
            (old_activity_id,),
        ).fetchone()
        boundary_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM session_boundary WHERE reason = 'maintenance_pause'"
            ).fetchone()[0]
        )
        inference_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM activity_inference_job WHERE activity_id = ?",
                (old_activity_id,),
            ).fetchone()[0]
        )
        open_rows = conn.execute(
            "SELECT id FROM activity_log WHERE end_time IS NULL"
        ).fetchall()
    assert durable is not None
    assert durable["end_time"] == "2026-07-19 10:02:00"
    assert durable["duration_seconds"] == 120
    assert boundary_count == 0
    assert inference_count == 1
    assert len(open_rows) == 1
    assert int(open_rows[0]["id"]) != old_activity_id
    assert control.restore_observed is True


@pytest.mark.parametrize("status", ["normal", "idle", "excluded"])
def test_maintenance_seals_active_status_without_session_boundary(temp_db, status):
    machine = _active_machine(status, "2026-07-19 11:00:00")
    activity_id = int(machine.recorder.persisted_activity_id or 0)

    machine.quiesce_for_maintenance("2026-07-19 11:00:45")
    machine.quiesce_for_maintenance("2026-07-19 11:00:46")

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT end_time, duration_seconds, status FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        boundaries = int(conn.execute("SELECT COUNT(*) FROM session_boundary").fetchone()[0])
        jobs = int(
            conn.execute(
                "SELECT COUNT(*) FROM activity_inference_job WHERE activity_id = ?",
                (activity_id,),
            ).fetchone()[0]
        )
    assert row is not None
    assert row["end_time"] == "2026-07-19 11:00:45"
    assert row["duration_seconds"] == 45
    assert row["status"] == status
    assert boundaries == 0
    assert jobs == (1 if status == "normal" else 0)


def test_maintenance_does_not_change_existing_user_pause(temp_db):
    machine = _active_machine("normal", "2026-07-19 12:00:00")
    machine.pause("2026-07-19 12:01:00")
    with db.get_connection() as conn:
        before = int(conn.execute("SELECT COUNT(*) FROM session_boundary").fetchone()[0])

    machine.quiesce_for_maintenance("2026-07-19 12:02:00")

    with db.get_connection() as conn:
        after = int(conn.execute("SELECT COUNT(*) FROM session_boundary").fetchone()[0])
    assert after == before
    assert settings_service.get_bool_setting("user_paused", False) is True
    assert settings_service.get_setting("collector_status", "") == "paused"


def test_replacement_clears_stale_runtime_activity_identity(
    temp_db,
    tmp_path,
    monkeypatch,
):
    machine = _active_machine("normal", "2026-07-19 13:00:00")
    old_activity_id = int(machine.recorder.persisted_activity_id or 0)
    runtime_activity_state_service.publish_runtime_activity_snapshot(
        {"persisted_activity_id": old_activity_id},
        "before_replacement",
    )
    control = _MachineRuntimeControl(
        machine,
        quiesce_at="2026-07-19 13:01:00",
        resume_at="2026-07-19 13:01:01",
    )
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")
    monkeypatch.setattr(
        database_maintenance_service.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    database_maintenance_service.register_runtime_control(control)
    out = tmp_path / "replace.wtbackup"
    try:
        secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
        secure_backup_service.import_encrypted_backup(out, PASSPHRASE)
    finally:
        database_maintenance_service.clear_runtime_control(control)

    snapshot = runtime_activity_state_service.sample_runtime_activity_state().snapshot
    assert control.reset_observed is True
    assert snapshot is not None
    assert int(snapshot["persisted_activity_id"]) != old_activity_id
