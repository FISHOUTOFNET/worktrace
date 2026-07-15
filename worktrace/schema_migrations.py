"""Sequential, explicit WorkTrace schema migrations.

Migrations only cover published supported versions. They run before background
workers start, must be deterministic, and may not infer repairs for an unknown
schema fingerprint.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

MIN_SUPPORTED_SCHEMA_VERSION = 4

Migration = Callable[[sqlite3.Connection], None]


def migrate_4_to_5(conn: sqlite3.Connection) -> None:
    """Remove transient collector state that no longer belongs in SQLite."""

    conn.executemany(
        "DELETE FROM settings WHERE key = ?",
        [
            ("current_activity_snapshot",),
            ("pending_short_seconds",),
            ("pending_short_carry_provenance",),
        ],
    )


MIGRATIONS: dict[int, Migration] = {
    4: migrate_4_to_5,
}


def migrate_schema(
    conn: sqlite3.Connection,
    *,
    current_version: int,
    target_version: int,
) -> int:
    """Apply every migration in order and return the resulting version."""

    version = int(current_version)
    target = int(target_version)
    if version < MIN_SUPPORTED_SCHEMA_VERSION or version > target:
        raise ValueError("database_schema_incompatible")
    while version < target:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ValueError("database_schema_incompatible")
        savepoint = f"worktrace_migration_{version}_to_{version + 1}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            migration(conn)
            version += 1
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
    return version


__all__ = [
    "MIGRATIONS",
    "MIN_SUPPORTED_SCHEMA_VERSION",
    "migrate_4_to_5",
    "migrate_schema",
]
