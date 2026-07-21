from __future__ import annotations

import hashlib
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.support.application import TestRuntimeMaintenanceControl
from tests.support.write_gate import (
    reset_global_write_gate_for_test,
    write_gate_state,
)
from worktrace import db
from worktrace.services import privacy_gate_service
from worktrace.write_gate import WriteGatePhase


class _FastTestScrypt:
    """Deterministic KDF stand-in for backup service orchestration tests."""

    def __init__(self, *, salt: bytes, length: int, n: int, r: int, p: int) -> None:
        self._salt = bytes(salt)
        self._length = int(length)
        self._parameters = f"{int(n)}:{int(r)}:{int(p)}".encode("ascii")

    def derive(self, key_material: bytes) -> bytes:
        seed = b"\0".join((self._salt, bytes(key_material), self._parameters))
        output = bytearray()
        counter = 0
        while len(output) < self._length:
            output.extend(
                hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            )
            counter += 1
        return bytes(output[: self._length])


@pytest.fixture(scope="session")
def _initialized_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the canonical empty test database once per pytest process."""

    template_dir = tmp_path_factory.mktemp("worktrace-db-template")
    template_path = template_dir / "worktrace-template.db"
    db.initialize_database(template_path)
    with db.get_connection() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return template_path


@pytest.fixture()
def temp_db(tmp_path: Path, _initialized_db_template: Path) -> Path:
    """Provide an isolated canonical database without rebuilding its schema."""

    path = tmp_path / "worktrace.db"
    shutil.copyfile(_initialized_db_template, path)
    db.configure_database(path)
    # Accept the installation-scoped privacy notice so integration tests that
    # exercise sensitive runtime observation (folder scans, collector loops)
    # match the normal production state after user consent. Tests that need to
    # verify "not accepted" behavior override the gate via monkeypatch.
    privacy_gate_service.accept_privacy_notice()
    return path


@pytest.fixture(autouse=True)
def _isolate_database_write_gate(request: pytest.FixtureRequest):
    """Reset the process gate and report any state leaked by the preceding test."""

    reset_global_write_gate_for_test()
    yield
    phase, reason = write_gate_state()
    if phase is not WriteGatePhase.OPEN or reason is not None:
        request.node.user_properties.append(
            ("write_gate_pollution", f"phase={phase.value};reason={reason or ''}")
        )
    reset_global_write_gate_for_test()
    clean_phase, clean_reason = write_gate_state()
    assert clean_phase is WriteGatePhase.OPEN
    assert clean_reason is None


@pytest.fixture(autouse=True)
def _isolate_maintenance_coordinator(monkeypatch: pytest.MonkeyPatch):
    """Compose every test with a fresh coordinator and explicit stopped runtime."""

    from worktrace.services import database_maintenance_service

    coordinator = database_maintenance_service.RuntimeMaintenanceCoordinator()
    coordinator.register_runtime_control(TestRuntimeMaintenanceControl())
    monkeypatch.setattr(
        database_maintenance_service,
        "MAINTENANCE_COORDINATOR",
        coordinator,
    )
    yield coordinator


@pytest.fixture(autouse=True)
def _accelerate_backup_service_kdf(request: pytest.FixtureRequest) -> Iterator[None]:
    """Keep service integration tests focused on backup orchestration semantics."""

    if Path(str(request.node.fspath)).name != "test_secure_backup_service.py":
        yield
        return

    from worktrace.security import kdf

    patcher = pytest.MonkeyPatch()
    patcher.setattr(kdf, "Scrypt", _FastTestScrypt)
    try:
        yield
    finally:
        patcher.undo()
