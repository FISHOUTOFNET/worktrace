from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.atomic_file import OwnedTemporaryFile, TemporaryFileCleanupError
from worktrace.services import maintenance_recovery_latch_repository
from worktrace.services.database_maintenance_service import (
    MaintenancePhase,
    MaintenanceRecoveryError,
    RuntimeMaintenanceCoordinator,
)
from worktrace.services.settings_service import set_settings
from worktrace.write_gate import DATABASE_WRITE_GATE

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.security_privacy,
    pytest.mark.contract,
    pytest.mark.serial,
]


class _OperationalHoldState:
    value = "operational"


class _OperationalControl:
    def __init__(self) -> None:
        self.collector_control = self
        self.hold_state = _OperationalHoldState()

    def query_command(self, command_id: str):
        return None

    def is_collection_running_for_maintenance(self) -> bool:
        return False

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        raise AssertionError("explicit recovery must not request hold")

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        raise AssertionError("explicit recovery must not reset replacement")

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        raise AssertionError("explicit recovery must not release")


def _reset_process_gate(coordinator: RuntimeMaintenanceCoordinator) -> None:
    DATABASE_WRITE_GATE._clear_recovery_block()
    coordinator._set_phase(MaintenancePhase.IDLE)


def test_active_sensitive_staging_is_not_misclassified_as_restart_residue(temp_db):
    with OwnedTemporaryFile(
        prefix="worktrace-import-",
        suffix=".sqlite",
        resource="decrypted_backup_staging",
        sensitive=True,
    ) as owner:
        owner.path.write_bytes(b"plaintext-staging")
        latch = maintenance_recovery_latch_repository.read_latch()
        assert latch.blocked is False
        assert latch.sensitive_residue_present is False

    assert maintenance_recovery_latch_repository.read_latch().blocked is False


def test_sensitive_cleanup_failure_becomes_restart_detectable_residue(
    temp_db,
    monkeypatch,
):
    owner = OwnedTemporaryFile(
        prefix="worktrace-import-",
        suffix=".sqlite",
        resource="decrypted_backup_staging",
        sensitive=True,
    )
    owner.__enter__()
    owner.path.write_bytes(b"plaintext-staging")
    staging_path = owner.path
    original_unlink = Path.unlink

    def fail_target_unlink(path: Path, *args, **kwargs):
        if path == staging_path:
            raise PermissionError("injected_sensitive_cleanup_failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_target_unlink)
    with pytest.raises(TemporaryFileCleanupError) as failure:
        owner.cleanup()
    assert failure.value.requires_recovery_block is True

    latch = maintenance_recovery_latch_repository.read_latch()
    assert latch.blocked is True
    assert latch.sensitive_residue_present is True
    assert latch.reason == "maintenance_sensitive_staging_cleanup_required"

    monkeypatch.setattr(Path, "unlink", original_unlink)
    staging_path.unlink(missing_ok=True)


def test_explicit_recovery_clears_residue_only_state(temp_db):
    directory = maintenance_recovery_latch_repository.sensitive_staging_directory()
    directory.mkdir(parents=True, exist_ok=True)
    residue = directory / "worktrace-import-crash.sqlite"
    residue.write_bytes(b"plaintext-staging")

    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_OperationalControl())
    assert coordinator.hydrate_fail_closed_from_durable() is True
    assert coordinator.recovery_blocked() is True

    coordinator.recover_fail_closed()

    assert residue.exists() is False
    assert maintenance_recovery_latch_repository.marker_path().exists() is False
    assert coordinator.recovery_blocked() is False
    assert coordinator.phase is MaintenancePhase.IDLE


def test_explicit_recovery_can_reseal_invalid_marker(temp_db):
    marker = maintenance_recovery_latch_repository.marker_path()
    marker.write_text("not-json", encoding="utf-8")
    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_OperationalControl())
    assert coordinator.hydrate_fail_closed_from_durable() is True

    coordinator.recover_fail_closed()

    assert marker.exists() is False
    assert coordinator.recovery_blocked() is False
    assert coordinator.phase is MaintenancePhase.IDLE


def test_valid_marker_with_sensitive_residue_reports_both(temp_db):
    directory = maintenance_recovery_latch_repository.sensitive_staging_directory()
    directory.mkdir(parents=True, exist_ok=True)
    residue = directory / "worktrace-import-crash.sqlite"
    residue.write_bytes(b"plaintext-staging")
    try:
        sealed = maintenance_recovery_latch_repository.arm_recovery(
            "coexistence_valid"
        )
        latch = maintenance_recovery_latch_repository.read_latch()

        assert latch.blocked is True
        assert latch.marker_present is True
        assert latch.sensitive_residue_present is True
        assert latch.epoch is not None
        assert latch.epoch == sealed.epoch
        assert latch.reason == "coexistence_valid"
    finally:
        maintenance_recovery_latch_repository.marker_path().unlink(missing_ok=True)
        residue.unlink(missing_ok=True)


def test_invalid_marker_with_sensitive_residue_reports_both(temp_db):
    directory = maintenance_recovery_latch_repository.sensitive_staging_directory()
    directory.mkdir(parents=True, exist_ok=True)
    residue = directory / "worktrace-import-crash.sqlite"
    residue.write_bytes(b"plaintext-staging")
    marker = maintenance_recovery_latch_repository.marker_path()
    marker.write_text("not-json", encoding="utf-8")
    try:
        latch = maintenance_recovery_latch_repository.read_latch()

        assert latch.blocked is True
        assert latch.marker_present is True
        assert latch.sensitive_residue_present is True
        assert latch.epoch is None
        assert latch.state == "invalid"
    finally:
        marker.unlink(missing_ok=True)
        residue.unlink(missing_ok=True)


def test_explicit_recovery_clears_residue_then_marker_when_both_present(temp_db):
    directory = maintenance_recovery_latch_repository.sensitive_staging_directory()
    directory.mkdir(parents=True, exist_ok=True)
    residue = directory / "worktrace-import-crash.sqlite"
    residue.write_bytes(b"plaintext-staging")
    maintenance_recovery_latch_repository.arm_recovery("coexistence_clear")

    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_OperationalControl())
    assert coordinator.hydrate_fail_closed_from_durable() is True
    assert coordinator.recovery_blocked() is True

    coordinator.recover_fail_closed()

    assert coordinator.recovery_blocked() is False
    assert coordinator.phase is MaintenancePhase.IDLE
    assert residue.exists() is False
    assert maintenance_recovery_latch_repository.marker_path().exists() is False
    assert DATABASE_WRITE_GATE.recovery_blocked() is False


def test_explicit_recovery_residue_cleanup_failure_keeps_fail_closed(
    temp_db,
    monkeypatch,
):
    directory = maintenance_recovery_latch_repository.sensitive_staging_directory()
    directory.mkdir(parents=True, exist_ok=True)
    residue = directory / "worktrace-import-crash.sqlite"
    residue.write_bytes(b"plaintext-staging")
    maintenance_recovery_latch_repository.arm_recovery("coexistence_residue_fail")

    coordinator = RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(_OperationalControl())
    assert coordinator.hydrate_fail_closed_from_durable() is True
    assert coordinator.recovery_blocked() is True

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "clear_sensitive_staging_residue",
        lambda: False,
    )

    try:
        with pytest.raises(MaintenanceRecoveryError):
            coordinator.recover_fail_closed()

        assert coordinator.recovery_blocked() is True
        assert coordinator.phase is MaintenancePhase.FAILED_CLOSED
        assert maintenance_recovery_latch_repository.marker_path().exists() is True
        assert residue.exists() is True
        assert DATABASE_WRITE_GATE.recovery_blocked() is True
    finally:
        _reset_process_gate(coordinator)
        maintenance_recovery_latch_repository.marker_path().unlink(missing_ok=True)
        residue.unlink(missing_ok=True)


def _create_residue() -> Path:
    directory = maintenance_recovery_latch_repository.sensitive_staging_directory()
    directory.mkdir(parents=True, exist_ok=True)
    residue = directory / "worktrace-import-evidence.sqlite"
    residue.write_bytes(b"plaintext-staging")
    return residue


def _set_mirror(reason: str = "mirror_reason") -> None:
    set_settings(
        {
            "maintenance_fail_closed": "true",
            "maintenance_fail_closed_reason": reason,
        }
    )


def _clear_mirror() -> None:
    set_settings(
        {
            "maintenance_fail_closed": "false",
            "maintenance_fail_closed_reason": "",
        }
    )


def test_valid_marker_with_mirror_and_residue_reports_all_three(temp_db):
    residue = _create_residue()
    try:
        maintenance_recovery_latch_repository.arm_recovery("valid_mirror_residue")
        _set_mirror("valid_mirror_residue")

        latch = maintenance_recovery_latch_repository.read_latch()

        assert latch.blocked is True
        assert latch.marker_present is True
        assert latch.database_mirror_present is True
        assert latch.sensitive_residue_present is True
        assert latch.reason == "valid_mirror_residue"
    finally:
        _clear_mirror()
        maintenance_recovery_latch_repository.marker_path().unlink(missing_ok=True)
        residue.unlink(missing_ok=True)


def test_valid_marker_without_mirror_with_residue_reports_absent_mirror(temp_db):
    residue = _create_residue()
    try:
        maintenance_recovery_latch_repository.arm_recovery("valid_no_mirror")

        latch = maintenance_recovery_latch_repository.read_latch()

        assert latch.blocked is True
        assert latch.marker_present is True
        assert latch.database_mirror_present is False
        assert latch.sensitive_residue_present is True
        assert latch.reason == "valid_no_mirror"
    finally:
        maintenance_recovery_latch_repository.marker_path().unlink(missing_ok=True)
        residue.unlink(missing_ok=True)


def test_invalid_marker_with_mirror_and_residue_reports_all_three(temp_db):
    residue = _create_residue()
    marker = maintenance_recovery_latch_repository.marker_path()
    marker.write_text("not-json", encoding="utf-8")
    try:
        _set_mirror("invalid_mirror_reason")

        latch = maintenance_recovery_latch_repository.read_latch()

        assert latch.blocked is True
        assert latch.marker_present is True
        assert latch.database_mirror_present is True
        assert latch.sensitive_residue_present is True
        assert latch.state == "invalid"
    finally:
        _clear_mirror()
        marker.unlink(missing_ok=True)
        residue.unlink(missing_ok=True)


def test_invalid_marker_without_mirror_with_residue_reports_absent_mirror(temp_db):
    residue = _create_residue()
    marker = maintenance_recovery_latch_repository.marker_path()
    marker.write_text("not-json", encoding="utf-8")
    try:
        latch = maintenance_recovery_latch_repository.read_latch()

        assert latch.blocked is True
        assert latch.marker_present is True
        assert latch.database_mirror_present is False
        assert latch.sensitive_residue_present is True
        assert latch.state == "invalid"
    finally:
        marker.unlink(missing_ok=True)
        residue.unlink(missing_ok=True)


def test_no_marker_with_mirror_and_residue_reports_mirror_and_residue(temp_db):
    residue = _create_residue()
    try:
        _set_mirror("no_marker_mirror")

        latch = maintenance_recovery_latch_repository.read_latch()

        assert latch.blocked is True
        assert latch.marker_present is False
        assert latch.database_mirror_present is True
        assert latch.sensitive_residue_present is True
        assert latch.reason == "no_marker_mirror"
    finally:
        _clear_mirror()
        residue.unlink(missing_ok=True)


def test_marker_present_but_mirror_read_exception_fails_closed(
    temp_db,
    monkeypatch,
):
    maintenance_recovery_latch_repository.arm_recovery("mirror_exc")

    def raising_mirror_read():
        raise RuntimeError("database mirror unreadable")

    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "_read_database_mirror",
        raising_mirror_read,
    )

    try:
        latch = maintenance_recovery_latch_repository.read_latch()

        assert latch.blocked is True
        assert latch.marker_present is True
    finally:
        maintenance_recovery_latch_repository.marker_path().unlink(missing_ok=True)
