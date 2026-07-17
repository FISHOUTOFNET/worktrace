"""SQLite access boundary: generic write exclusion plus explicit domain UoW ownership."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar

from . import db_storage as _storage
from .db_storage import *  # noqa: F401,F403
from .write_gate import DATABASE_WRITE_GATE

_INITIALIZE_DATABASE_IMPL = _storage.initialize_database
_APPLY_CURRENT_SCHEMA_IMPL = _storage.apply_current_schema
_SEED_DEFAULTS_IMPL = _storage.seed_defaults
_ENSURE_CURRENT_INDEXES_IMPL = _storage.ensure_current_indexes
_RESET_DATABASE_IMPL = _storage.reset_database

_INFRASTRUCTURE_WRITE_SCOPE: ContextVar[bool] = ContextVar(
    "worktrace_infrastructure_write_scope",
    default=False,
)


@contextmanager
def infrastructure_write_scope():
    token = _INFRASTRUCTURE_WRITE_SCOPE.set(True)
    try:
        yield
    finally:
        _INFRASTRUCTURE_WRITE_SCOPE.reset(token)


def _is_write_statement(sql: str) -> bool:
    return bool(_storage._sql_requires_write_gate(str(sql)))


def _is_transaction_control(sql: str) -> bool:
    upper = str(sql or "").lstrip().upper()
    return upper.startswith(
        ("BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE", "PRAGMA")
    )


class WorkTraceConnection(sqlite3.Connection):
    """Connection with no domain-table knowledge; UoW owners declare effects."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._domain_write_occurred = False
        self._infrastructure_write_occurred = False

    def _require_write_allowed(self, sql: str) -> None:
        if _is_write_statement(sql):
            DATABASE_WRITE_GATE.require_current_thread_allowed()

    def _capture_write(self, sql: str, rowcount: int | None) -> None:
        if rowcount == 0 or not _is_write_statement(sql) or _is_transaction_control(sql):
            return
        self._domain_write_occurred = True
        if _INFRASTRUCTURE_WRITE_SCOPE.get():
            self._infrastructure_write_occurred = True

    def _require_owned_write(self) -> None:
        if not self._domain_write_occurred or self._infrastructure_write_occurred:
            return
        from .domain_unit_of_work import current_domain_unit_of_work

        if current_domain_unit_of_work() is None:
            raise RuntimeError("domain_unit_of_work_required")

    def _reset_write_state(self) -> None:
        self._domain_write_occurred = False
        self._infrastructure_write_occurred = False

    def execute(self, sql, parameters=(), /):  # type: ignore[override]
        text = str(sql)
        self._require_write_allowed(text)
        cursor = sqlite3.Connection.execute(self, sql, parameters)
        self._capture_write(text, cursor.rowcount)
        if _storage._sql_records_business_read(text):
            DATABASE_WRITE_GATE.note_current_thread_read()
        return cursor

    def executemany(self, sql, seq_of_parameters, /):  # type: ignore[override]
        text = str(sql)
        self._require_write_allowed(text)
        cursor = sqlite3.Connection.executemany(self, sql, seq_of_parameters)
        self._capture_write(text, cursor.rowcount)
        return cursor

    def executescript(self, sql_script, /):  # type: ignore[override]
        text = str(sql_script)
        self._require_write_allowed(text)
        cursor = sqlite3.Connection.executescript(self, sql_script)
        self._capture_write(text, cursor.rowcount)
        return cursor

    def commit(self) -> None:  # type: ignore[override]
        self._require_owned_write()
        sqlite3.Connection.commit(self)
        self._reset_write_state()

    def rollback(self) -> None:  # type: ignore[override]
        sqlite3.Connection.rollback(self)
        self._reset_write_state()

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self._require_owned_write()
        try:
            return sqlite3.Connection.__exit__(self, exc_type, exc_value, traceback)
        finally:
            self._reset_write_state()


def _open_connection() -> sqlite3.Connection:
    database_path = get_db_path()
    conn = sqlite3.connect(
        database_path,
        timeout=5,
        check_same_thread=False,
        factory=WorkTraceConnection,
    )
    conn.row_factory = sqlite3.Row
    apply_connection_pragmas(conn)
    return conn


def get_connection():
    from .domain_unit_of_work import current_domain_unit_of_work

    unit_of_work = current_domain_unit_of_work()
    if unit_of_work is not None:
        return unit_of_work.lease()
    return _open_connection()


def initialize_database(path=None) -> None:
    with infrastructure_write_scope():
        _INITIALIZE_DATABASE_IMPL(path)


def apply_current_schema(conn) -> None:
    with infrastructure_write_scope():
        _APPLY_CURRENT_SCHEMA_IMPL(conn)


def seed_defaults(conn) -> None:
    with infrastructure_write_scope():
        _SEED_DEFAULTS_IMPL(conn)


def ensure_current_indexes(conn) -> None:
    with infrastructure_write_scope():
        _ENSURE_CURRENT_INDEXES_IMPL(conn)


def reset_database() -> None:
    with infrastructure_write_scope():
        _RESET_DATABASE_IMPL()


# Schema/bootstrap functions resolve these globals in db_storage at call time.
_storage.WorkTraceConnection = WorkTraceConnection
_storage.get_connection = get_connection
_storage.initialize_database = initialize_database
_storage.apply_current_schema = apply_current_schema
_storage.seed_defaults = seed_defaults
_storage.ensure_current_indexes = ensure_current_indexes
_storage.reset_database = reset_database


def __getattr__(name: str):
    return getattr(_storage, name)
