"""Ordered schema migrations with frozen historical implementations."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from . import schema_migrations_core as _core

MIN_SUPPORTED_SCHEMA_VERSION = _core.MIN_SUPPORTED_SCHEMA_VERSION
Migration = Callable[[sqlite3.Connection], None]

migrate_4_to_5 = _core.migrate_4_to_5
migrate_5_to_6 = _core.migrate_5_to_6
migrate_6_to_7 = _core.migrate_6_to_7
migrate_7_to_8 = _core.migrate_7_to_8
migrate_8_to_9 = _core.migrate_8_to_9
migrate_9_to_10 = _core.migrate_9_to_10


def migrate_10_to_11(conn: sqlite3.Connection) -> None:
    """Create the minimal outbox and seed only legacy unresolved assignments."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_inference_job (
            activity_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL CHECK(
                reason IN (
                    'finalize', 'facts_changed',
                    'migration_repair', 'import_repair'
                )
            ),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            available_at TEXT NOT NULL,
            last_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(activity_id) REFERENCES activity_log(id) ON DELETE CASCADE
        )
        """
    )
    now = str(
        conn.execute("SELECT datetime('now', 'localtime')").fetchone()[0]
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO activity_inference_job(
            activity_id, reason, attempt_count, available_at,
            last_error_code, created_at, updated_at
        )
        SELECT
            activity.id, 'migration_repair', 0, ?, NULL, ?, ?
        FROM activity_log activity
        LEFT JOIN activity_project_assignment assignment
          ON assignment.activity_id = activity.id
        WHERE activity.end_time IS NOT NULL
          AND activity.status = 'normal'
          AND activity.is_hidden = 0
          AND activity.is_deleted = 0
          AND (
                assignment.activity_id IS NULL
                OR (
                    assignment.is_manual = 0
                    AND assignment.source IN (
                        'uncategorized', 'suggested_project_name'
                    )
                )
          )
        """,
        (now, now, now),
    )


MIGRATIONS: dict[int, Migration] = {
    **_core.MIGRATIONS,
    10: migrate_10_to_11,
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
    "migrate_5_to_6",
    "migrate_6_to_7",
    "migrate_7_to_8",
    "migrate_8_to_9",
    "migrate_9_to_10",
    "migrate_10_to_11",
    "migrate_schema",
]
