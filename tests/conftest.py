from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worktrace import db


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
def _initialized_db_template(tmp_path_factory) -> Path:
    """Build the canonical empty test database once per pytest process."""

    template_dir = tmp_path_factory.mktemp("worktrace-db-template")
    template_path = template_dir / "worktrace-template.db"
    db.initialize_database(template_path)
    with db.get_connection() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return template_path


@pytest.fixture()
def temp_db(tmp_path, _initialized_db_template):
    """Provide an isolated canonical database without rebuilding its schema."""

    path = tmp_path / "worktrace.db"
    shutil.copyfile(_initialized_db_template, path)
    db.configure_database(path)
    return path


@pytest.fixture(autouse=True)
def _accelerate_backup_service_kdf(request):
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
