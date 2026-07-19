from __future__ import annotations

import hashlib
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.support.application import build_test_application_services
from worktrace import db
from worktrace.webview_ui import bridge as bridge_module


_ProductionWebViewBridge = bridge_module.WebViewBridge


class _ComposedTestWebViewBridge(_ProductionWebViewBridge):
    """Test-only composition root with explicit fake application capabilities."""

    def __init__(self, services: Any | None = None) -> None:
        super().__init__(services or build_test_application_services())


# Test modules importing WebViewBridge receive a fully composed test bridge.
# The production class remains strict and has no optional dependency fallback.
bridge_module.WebViewBridge = _ComposedTestWebViewBridge


class _FastTestScrypt:
    """Deterministic KDF stand-in for backup service orchestration tests.

    The production KDF implementation and its resource parameters remain covered
    by the dedicated backup-format tests. Service integration tests exercise the
    manifest, authenticated encryption, wrong-passphrase, corruption, import,
    and replacement contracts without repeatedly paying the production scrypt
    work factor.
    """

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
    return path


@pytest.fixture(autouse=True)
def _isolate_maintenance_coordinator(monkeypatch: pytest.MonkeyPatch):
    """Give every test a fresh canonical maintenance state machine.

    Fail-closed is intentionally stable in production. Tests that exercise it
    must not leak that process-global latch into unrelated cases.
    """

    from worktrace.services import database_maintenance_service

    coordinator = database_maintenance_service.RuntimeMaintenanceCoordinator()
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
