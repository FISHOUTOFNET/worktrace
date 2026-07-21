from __future__ import annotations

import sqlite3

from worktrace import db
from worktrace.database_content_manifest import DELETE_ORDER, TABLE_NAMES

_DROP_ORDER: tuple[str, ...] = DELETE_ORDER + tuple(
    name for name in TABLE_NAMES if name not in frozenset(DELETE_ORDER)
)


def drop_all_tables(conn: sqlite3.Connection) -> None:
    """Destroy the test database schema without exposing a production entrypoint."""

    for table in _DROP_ORDER:
        conn.execute(f"DROP TABLE IF EXISTS {table}")


def reset_database() -> None:
    """Rebuild the configured test database using the exact current schema."""

    with db.get_connection() as conn:
        db.ensure_wal(conn)
        drop_all_tables(conn)
        db.apply_current_schema(conn)
        db.seed_defaults(conn)
