"""Sequential, explicit WorkTrace schema migrations.

Published historical migrations are retained verbatim in
``schema_migrations_history``. This module owns the active compatibility chain
and the current v10-to-v11 durable inference boundary.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .schema_migrations_history import (
    MIN_SUPPORTED_SCHEMA_VERSION,
    migrate_4_to_5,
    migrate_5_to_6,
    migrate_6_to_7,
    migrate_7_to_8,
    migrate_8_to_9,
    migrate_9_to_10,
)

Migration = Callable[[sqlite3.Connection], None]


def migrate_10_to_11(conn: sqlite3.Connection) -> None:
    """Replace assignment sentinels with durable inference obligations."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_inference_job (
            activity_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL CHECK(
                reason IN ('closed_activity', 'legacy_retry')
            ),
            status TEXT NOT NULL CHECK(status IN ('pending', 'failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            next_attempt_at TEXT,
            last_error_code TEXT CHECK(
                last_error_code IS NULL OR last_error_code IN (
                    'data_repair_required',
                    'database_busy',
                    'database_generation_changed',
                    'secure_import_in_progress',
                    'unexpected_failure'
                )
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(activity_id) REFERENCES activity_log(id) ON DELETE CASCADE
        )
        """
    )
    timestamp = str(
        conn.execute("SELECT datetime('now', 'localtime')").fetchone()[0]
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO activity_inference_job(
            activity_id, reason, status, attempt_count, next_attempt_at,
            last_error_code, created_at, updated_at
        )
        SELECT
            activity.id, 'legacy_retry', 'pending', 0, NULL, NULL, ?, ?
        FROM activity_log activity
        JOIN activity_project_assignment assignment
          ON assignment.activity_id = activity.id
        WHERE activity.end_time IS NOT NULL
          AND activity.status = 'normal'
          AND activity.is_hidden = 0
          AND activity.is_deleted = 0
          AND assignment.is_manual = 0
          AND assignment.source = 'uncategorized'
          AND assignment.confidence = -1
        """,
        (timestamp, timestamp),
    )
    conn.execute(
        """
        UPDATE activity_project_assignment
        SET confidence = 0, updated_at = ?
        WHERE is_manual = 0
          AND source = 'uncategorized'
          AND confidence = -1
        """,
        (timestamp,),
    )


MIGRATIONS: dict[int, Migration] = {
    4: migrate_4_to_5,
    5: migrate_5_to_6,
    6: migrate_6_to_7,
    7: migrate_7_to_8,
    8: migrate_8_to_9,
    9: migrate_9_to_10,
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
