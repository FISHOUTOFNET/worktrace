from __future__ import annotations

import sqlite3

import pytest

from worktrace import db as db_module
from worktrace import domain_unit_of_work as domain_module
from worktrace import database_replacement_unit_of_work as replacement_module
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.database_replacement_unit_of_work import (
    DatabaseReplacementUnitOfWork,
    ReplacementUnitOfWorkState,
)
from worktrace.domain_unit_of_work import DomainUnitOfWork, UnitOfWorkState

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


class _ConnectionProxy:
    def __init__(self, connection, *, fail_rollback=False, fail_close=False):
        self._connection = connection
        self._fail_rollback = fail_rollback
        self._fail_close = fail_close

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def rollback(self):
        self._connection.rollback()
        if self._fail_rollback:
            raise RuntimeError("injected_rollback_failure")

    def close(self):
        self._connection.close()
        if self._fail_close:
            raise RuntimeError("injected_close_failure")


def test_domain_close_failure_does_not_relabel_durable_commit(
    temp_db,
    monkeypatch,
):
    original_get_connection = db_module.get_connection
    monkeypatch.setattr(
        db_module,
        "get_connection",
        lambda: _ConnectionProxy(original_get_connection(), fail_close=True),
    )
    uow = DomainUnitOfWork()
    with uow:
        uow.connection.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES ('runtime.finalization_probe', 'committed', '2026-07-21 00:00:00')
            """
        )

    assert uow.state is UnitOfWorkState.FINALIZED
    assert uow.durable_committed is True
    assert uow.rolled_back is False
    with sqlite3.connect(temp_db) as conn:
        value = conn.execute(
            "SELECT value FROM settings WHERE key = 'runtime.finalization_probe'"
        ).fetchone()[0]
    assert value == "committed"


def test_domain_rollback_and_close_failures_preserve_primary_exception(
    temp_db,
    monkeypatch,
):
    original_get_connection = db_module.get_connection
    monkeypatch.setattr(
        db_module,
        "get_connection",
        lambda: _ConnectionProxy(
            original_get_connection(),
            fail_rollback=True,
            fail_close=True,
        ),
    )
    uow = DomainUnitOfWork()
    with pytest.raises(RuntimeError, match="primary_operation_failure"):
        with uow:
            uow.connection.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES ('runtime.rollback_probe', 'no', '2026-07-21 00:00:00')
                """
            )
            raise RuntimeError("primary_operation_failure")

    assert uow.state is UnitOfWorkState.FINALIZED
    assert uow.durable_committed is False
    assert uow.rolled_back is True
    with sqlite3.connect(temp_db) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'runtime.rollback_probe'"
        ).fetchone()
    assert row is None


def test_domain_context_reset_failure_uses_explicit_clear_fallback(
    temp_db,
    monkeypatch,
):
    class FailingContext:
        def __init__(self):
            self.current = None

        def get(self):
            return self.current

        def set(self, value):
            previous = self.current
            self.current = value
            return previous

        def reset(self, _token):
            raise RuntimeError("injected_context_reset_failure")

    context = FailingContext()
    monkeypatch.setattr(domain_module, "_CURRENT_UNIT_OF_WORK", context)
    with DomainUnitOfWork() as uow:
        assert domain_module.current_domain_unit_of_work() is uow
    assert context.current is None


def test_replacement_close_failure_retains_committed_outcome(
    temp_db,
    monkeypatch,
):
    original_get_connection = replacement_module.get_connection
    monkeypatch.setattr(
        replacement_module,
        "get_connection",
        lambda: _ConnectionProxy(original_get_connection(), fail_close=True),
    )
    with db_module.get_connection() as conn:
        before = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )

    uow = DatabaseReplacementUnitOfWork()
    with uow:
        uow.connection.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES ('runtime.replacement_probe', 'committed', '2026-07-21 00:00:00')
            """
        )

    assert uow.state is ReplacementUnitOfWorkState.FINALIZED
    assert uow.committed is True
    assert uow.rolled_back is False
    assert uow.committed_values is not None
    with db_module.get_connection() as conn:
        after = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )
        value = conn.execute(
            "SELECT value FROM settings WHERE key = 'runtime.replacement_probe'"
        ).fetchone()["value"]
    assert after == before + 1
    assert value == "committed"
