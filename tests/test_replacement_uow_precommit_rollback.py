from __future__ import annotations

import sqlite3

import pytest

from worktrace import database_replacement_unit_of_work as replacement_module
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.database_replacement_unit_of_work import (
    DatabaseReplacementUnitOfWork,
    ReplacementUnitOfWorkState,
)
from worktrace.db import get_connection

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


class _RollbackTrackingConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.rollback_calls = 0

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def rollback(self):
        self.rollback_calls += 1
        return self._connection.rollback()


def test_generation_bump_failure_explicitly_rolls_back_replacement(
    temp_db,
    monkeypatch,
):
    original_get_connection = replacement_module.get_connection
    tracked = _RollbackTrackingConnection(original_get_connection())
    monkeypatch.setattr(replacement_module, "get_connection", lambda: tracked)

    with get_connection() as conn:
        before = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )

    original_bump = DataGenerationRepository.bump_replacement

    def fail_after_bump(conn, *, minimum_value=None):
        original_bump(conn, minimum_value=minimum_value)
        raise RuntimeError("injected_generation_bump_failure")

    monkeypatch.setattr(
        DataGenerationRepository,
        "bump_replacement",
        staticmethod(fail_after_bump),
    )

    uow = DatabaseReplacementUnitOfWork()
    with pytest.raises(RuntimeError, match="injected_generation_bump_failure"):
        with uow:
            uow.connection.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES ('runtime.precommit_probe', 'not-committed',
                        '2026-07-21 00:00:00')
                """
            )

    assert tracked.rollback_calls == 1
    assert uow.state is ReplacementUnitOfWorkState.FINALIZED
    assert uow.committed is False
    assert uow.rolled_back is True
    with get_connection() as conn:
        after = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'runtime.precommit_probe'"
        ).fetchone()
    assert after == before
    assert row is None
