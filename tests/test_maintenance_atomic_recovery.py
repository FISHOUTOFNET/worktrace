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


def test_recovery_clear_failure_keeps_process_and_sidecar_blocks(
    temp_db,
    monkeypatch,
):
    _persist_blocked_latch()
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control())
    assert coordinator.hydrate_fail_closed_from_durable() is True

    def fail_clear(*, expected_epoch: str) -> None:
        assert expected_epoch
        raise RuntimeError("durable_clear_failed")

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "clear_latch",
        fail_clear,
    )

    with pytest.raises(
        MaintenanceRecoveryError,
        match="maintenance_recovery_not_verified",
    ):
        coordinator.recover_fail_closed()

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert DATABASE_WRITE_GATE.recovery_blocked() is True
    assert settings_service.get_bool_setting("maintenance_fail_closed", False) is True
    latch = maintenance_recovery_latch_repository.read_latch()
    assert latch.blocked is True
    assert latch.epoch


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
    assert maintenance_recovery_latch_repository.marker_path().exists() is False


def test_fail_closed_mirror_failure_keeps_armed_sidecar_and_process_gate(
    temp_db,
    monkeypatch,
):
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control(running=True, reset_ok=False))
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    def fail_persist(reason: str, *, expected_epoch: str | None = None):
        assert reason
        assert expected_epoch
        raise RuntimeError("persist_failed")

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "persist_fail_closed",
        fail_persist,
    )

    with pytest.raises(RuntimeError, match="collector_database_reset_not_acknowledged"):
        with coordinator.database_replacement("persist_failure"):
            pass

    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert DATABASE_WRITE_GATE.operation_active() is False
    assert DATABASE_WRITE_GATE.recovery_blocked() is True
    assert DATABASE_WRITE_GATE.writes_blocked() is True
    latch = maintenance_recovery_latch_repository.read_latch()
    assert latch.blocked is True
    assert latch.state == "armed"
    assert latch.epoch


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


def _install_clear_latch_marker_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate external marker deletion after clear_latch clears the mirror.

    ``clear_latch`` clears the SQLite mirror via ``set_settings`` before
    deleting the sidecar. This wrapper deletes the marker file right after
    the mirror is cleared, so the subsequent ``unlink`` raises
    ``FileNotFoundError`` — exactly the cross-restart fail-open window where
    both the mirror and the marker are gone while the process still blocks.
    """

    original_set_settings = maintenance_recovery_latch_repository.set_settings

    def set_settings_and_delete_marker(settings_dict):
        original_set_settings(settings_dict)
        if (
            isinstance(settings_dict, dict)
            and settings_dict.get("maintenance_fail_closed") == "false"
        ):
            marker = maintenance_recovery_latch_repository.marker_path()
            if marker.exists():
                marker.unlink()

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "set_settings",
        set_settings_and_delete_marker,
    )


def test_clear_latch_marker_loss_re_establishes_durable_evidence(
    temp_db, monkeypatch
):
    """Marker vanishing between verify and unlink must not leave disk clean.

    Simulates an external deletion of the recovery marker after clear_latch
    has read/verified it but before unlink. The SQLite mirror is already
    cleared by clear_latch at that point, so without re-establishment a
    restart would fail open. The coordinator must stay fail-closed and disk
    must regain recognizable durable evidence.
    """

    seal = maintenance_recovery_latch_repository.persist_fail_closed(
        "durable_blocked"
    )
    original_epoch = seal.epoch
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control())
    assert coordinator.hydrate_fail_closed_from_durable() is True

    _install_clear_latch_marker_loss(monkeypatch)

    with pytest.raises(
        MaintenanceRecoveryError,
        match="maintenance_recovery_not_verified",
    ):
        coordinator.recover_fail_closed()

    # Coordinator must not enter IDLE; process stays blocked.
    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert DATABASE_WRITE_GATE.recovery_blocked() is True

    # Disk must have re-established durable fail-closed evidence.
    latch = maintenance_recovery_latch_repository.read_latch()
    assert latch.blocked is True
    assert latch.marker_present is True
    assert latch.epoch is not None
    # The lost epoch must not be reused; a fresh epoch re-establishes evidence.
    assert latch.epoch != original_epoch


def test_simulated_restart_stays_blocked_after_marker_loss(temp_db, monkeypatch):
    """After clear_latch marker loss, a fresh process must rehydrate blocked.

    Resets all process-local state (phase, write-gate block, active staging
    ownership) to simulate a restart, then hydrates from durable evidence
    left by the re-establishment path. The new process must re-enter
    fail-closed and must not mistake the previously-cleared mirror for safe.
    """

    maintenance_recovery_latch_repository.persist_fail_closed("restart_blocked")
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control())
    assert coordinator.hydrate_fail_closed_from_durable() is True

    _install_clear_latch_marker_loss(monkeypatch)

    with pytest.raises(MaintenanceRecoveryError):
        coordinator.recover_fail_closed()

    # Disk must have durable evidence before we simulate the restart.
    evidence_before = maintenance_recovery_latch_repository.read_latch()
    assert evidence_before.blocked is True
    assert evidence_before.marker_present is True

    # Simulate restart: drop all process-local state. Disk evidence remains.
    DATABASE_WRITE_GATE._clear_recovery_block()
    coordinator._set_phase(MaintenancePhase.IDLE)
    with maintenance_recovery_latch_repository._ACTIVE_SENSITIVE_STAGING_LOCK:
        maintenance_recovery_latch_repository._ACTIVE_SENSITIVE_STAGING.clear()

    # A new coordinator/process hydrates from durable evidence only.
    restarted = RuntimeMaintenanceCoordinator()
    assert restarted.hydrate_fail_closed_from_durable() is True
    assert restarted.phase is MaintenancePhase.FAILED_CLOSED
    assert restarted.recovery_blocked() is True

    # read_latch must still report blocked via the re-established marker,
    # not misjudge safety from the previously-cleared SQLite mirror.
    latch = maintenance_recovery_latch_repository.read_latch()
    assert latch.blocked is True
    assert latch.marker_present is True


def test_ensure_fail_closed_evidence_failure_propagates(temp_db, monkeypatch):
    """When no durable evidence can be re-established, the exception must propagate.

    Marker gone, mirror cleared, no residue, and fresh marker creation fails.
    The coordinator must not swallow this or claim recovery complete.
    """

    maintenance_recovery_latch_repository.persist_fail_closed("evidence_failure")
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control())
    assert coordinator.hydrate_fail_closed_from_durable() is True

    _install_clear_latch_marker_loss(monkeypatch)

    # Also break fresh marker creation so ensure_fail_closed_evidence fails.
    def fail_atomic_write(*args, **kwargs):
        raise OSError("disk_unavailable")

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "atomic_write_text",
        fail_atomic_write,
    )

    with pytest.raises(
        MaintenanceRecoveryError,
        match="maintenance_recovery_durable_evidence_unavailable",
    ):
        coordinator.recover_fail_closed()

    # Coordinator must not enter IDLE and must stay blocked in-process.
    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert DATABASE_WRITE_GATE.recovery_blocked() is True

    # Disk has no durable evidence — but the caller saw a clear exception,
    # so it cannot claim recovery is complete.
    latch = maintenance_recovery_latch_repository.read_latch()
    assert latch.blocked is False
    assert latch.marker_present is False


def test_ensure_fail_closed_evidence_does_not_expand_existing_state(temp_db):
    """When durable evidence already exists, do not create extra markers or
    overwrite epochs. Verify each evidence kind independently.
    """

    marker_file = maintenance_recovery_latch_repository.marker_path()

    # Case 1: valid blocked marker exists — must keep its epoch untouched.
    marker_seal = maintenance_recovery_latch_repository.persist_fail_closed(
        "marker_exists"
    )
    marker_content_before = marker_file.read_text(encoding="utf-8")

    latch = maintenance_recovery_latch_repository.ensure_fail_closed_evidence(
        "should_not_overwrite"
    )
    assert latch.blocked is True
    assert latch.epoch == marker_seal.epoch
    assert marker_file.read_text(encoding="utf-8") == marker_content_before

    # Clean up marker for next case.
    marker_file.unlink()

    # Case 2: only the SQLite mirror is blocked (no marker) — must not
    # create a marker.
    settings_service.set_settings(
        {
            "maintenance_fail_closed": "true",
            "maintenance_fail_closed_reason": "mirror_only",
            "user_paused": "true",
            "collector_status": "paused",
        }
    )
    latch = maintenance_recovery_latch_repository.ensure_fail_closed_evidence(
        "should_not_create_marker"
    )
    assert latch.blocked is True
    assert latch.marker_present is False
    assert marker_file.exists() is False

    # Clean up mirror for next case.
    settings_service.set_settings(
        {"maintenance_fail_closed": "false", "maintenance_fail_closed_reason": ""}
    )

    # Case 3: only sensitive staging residue exists — must not create a marker.
    staging_dir = maintenance_recovery_latch_repository.sensitive_staging_directory()
    staging_dir.mkdir(parents=True, exist_ok=True)
    residue_file = staging_dir / "worktrace-import-residue.sqlite"
    residue_file.write_bytes(b"residue")
    try:
        latch = maintenance_recovery_latch_repository.ensure_fail_closed_evidence(
            "should_not_create_marker"
        )
        assert latch.blocked is True
        assert latch.sensitive_residue_present is True
        assert latch.marker_present is False
        assert marker_file.exists() is False
    finally:
        residue_file.unlink(missing_ok=True)


def test_persist_fail_closed_re_establishs_evidence_in_maintenance_flow(
    temp_db, monkeypatch
):
    """The maintenance operation path must also re-establish durable evidence.

    During a database replacement, clear_latch is called inside
    _verify_stable_runtime_and_clear_seal. If the marker vanishes between
    verify and unlink there, the post-body failure handoff enters
    fail-closed via _persist_fail_closed (carrying the stale armed epoch).
    _persist_fail_closed must re-establish fresh durable evidence instead
    of swallowing the epoch_missing error.
    """

    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_Control())
    settings_service.set_settings(
        {"user_paused": "false", "collector_status": "stopped"}
    )

    # Capture the armed epoch so we can verify the re-established epoch differs.
    armed_epochs: list[str] = []
    original_arm = maintenance_recovery_latch_repository.arm_recovery

    def tracking_arm(reason: str):
        seal = original_arm(reason)
        armed_epochs.append(seal.epoch)
        return seal

    monkeypatch.setattr(
        maintenance_recovery_latch_repository, "arm_recovery", tracking_arm
    )

    _install_clear_latch_marker_loss(monkeypatch)

    with pytest.raises(
        maintenance_recovery_latch_repository.MaintenanceRecoverySealError
    ):
        with coordinator.database_replacement("replacement_marker_loss"):
            pass  # body completes; fault triggers in post-body clear_latch

    assert armed_epochs  # arm_recovery was called
    original_epoch = armed_epochs[0]

    # Coordinator must not enter IDLE; process stays blocked.
    assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
    assert DATABASE_WRITE_GATE.recovery_blocked() is True

    # Disk must have re-established durable fail-closed evidence with a
    # fresh epoch (the armed epoch was lost with the deleted marker).
    latch = maintenance_recovery_latch_repository.read_latch()
    assert latch.blocked is True
    assert latch.marker_present is True
    assert latch.epoch is not None
    assert latch.epoch != original_epoch
