from __future__ import annotations

import sqlite3

from worktrace.api import errors


def test_sqlite_busy_and_locked_map_to_stable_database_busy_code():
    for exc in (
        sqlite3.OperationalError("database is locked"),
        sqlite3.OperationalError("database is busy"),
    ):
        assert errors.error_code_from_exception(exc) == errors.DATABASE_BUSY
        assert "database" not in errors.public_message_for_code(errors.DATABASE_BUSY).lower()
