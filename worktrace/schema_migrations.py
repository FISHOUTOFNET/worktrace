"""Sequential, explicit WorkTrace schema migrations.

Migrations only cover published supported versions. They run before background
workers start and must be deterministic.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

_CURRENT_SNAPSHOT_KEY = "current_activity_" + "snapshot"
_PENDING_SECONDS_KEY = "pending_short_" + "seconds"
_PENDING_PROVENANCE_KEY = "pending_short_carry_" + "provenance"

MIN_SUPPORTED_SCHEMA_VERSION = 4

Migration = Callable[[sqlite3.Connection], None]


def migrate_4_to_5(conn: sqlite3.Connection) -> None:
    """Remove transient collector state that no longer belongs in SQLite."""

    conn.executemany(
        "DELETE FROM settings WHERE key = ?",
        [
            (_CURRENT_SNAPSHOT_KEY,),
            (_PENDING_SECONDS_KEY,),
            (_PENDING_PROVENANCE_KEY,),
        ],
    )


def migrate_5_to_6(conn: sqlite3.Connection) -> None:
    """Add lifecycle invariants, resumable jobs and index generations."""

    # Every open row belongs to the process generation that created the v5
    # database. Migration runs before a new Collector starts, so seal all of
    # them at their last durable checkpoint before installing the unique index.
    conn.execute(
        """
        UPDATE activity_log
        SET end_time = CASE
                WHEN COALESCE(duration_seconds, 0) <= 0 THEN start_time
                ELSE datetime(
                    start_time,
                    '+' || CAST(COALESCE(duration_seconds, 0) AS TEXT) || ' seconds'
                )
            END,
            duration_seconds = MAX(0, COALESCE(duration_seconds, 0)),
            updated_at = COALESCE(updated_at, start_time)
        WHERE end_time IS NULL
        """
    )

    conn.execute("ALTER TABLE folder_rule_index_state ADD COLUMN active_generation INTEGER")
    conn.execute("ALTER TABLE folder_rule_index_state ADD COLUMN building_generation INTEGER")
    conn.execute(
        "ALTER TABLE folder_rule_index_state ADD COLUMN build_status TEXT "
        "CHECK(build_status IS NULL OR build_status IN "
        "('pending', 'indexing', 'ready', 'stale', 'error'))"
    )
    conn.execute("ALTER TABLE folder_rule_index_state ADD COLUMN last_error TEXT")

    conn.execute(
        "ALTER TABLE folder_rule_file_index RENAME TO folder_rule_file_index_v5"
    )
    conn.execute(
        """
        CREATE TABLE folder_rule_file_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_rule_id INTEGER NOT NULL,
            generation INTEGER NOT NULL DEFAULT 1,
            file_name TEXT NOT NULL,
            normalized_file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            normalized_path_key TEXT NOT NULL,
            mtime REAL,
            size INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (folder_rule_id) REFERENCES folder_project_rule(id) ON DELETE CASCADE,
            UNIQUE(folder_rule_id, generation, normalized_path_key)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO folder_rule_file_index(
            id, folder_rule_id, generation, file_name, normalized_file_name,
            file_path, normalized_path_key, mtime, size, created_at, updated_at
        )
        SELECT id, folder_rule_id, 1, file_name, normalized_file_name,
               file_path, normalized_path_key, mtime, size, created_at, updated_at
        FROM folder_rule_file_index_v5
        """
    )
    conn.execute("DROP TABLE folder_rule_file_index_v5")
    conn.execute(
        """
        UPDATE folder_rule_index_state
        SET active_generation = CASE
                WHEN EXISTS (
                    SELECT 1 FROM folder_rule_file_index idx
                    WHERE idx.folder_rule_id = folder_rule_index_state.folder_rule_id
                ) THEN 1 ELSE NULL END,
            building_generation = NULL,
            build_status = status,
            last_error = error_message
        """
    )

    conn.executescript(
        """
        CREATE TABLE history_mutation_job (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (
                kind IN ('rule_backfill', 'rule_remove', 'rule_delete')
            ),
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'running', 'completed', 'failed', 'cancelled')
            ),
            payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
            cutoff_activity_id INTEGER NOT NULL DEFAULT 0,
            cursor_activity_id INTEGER NOT NULL DEFAULT 0,
            processed_count INTEGER NOT NULL DEFAULT 0,
            changed_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE history_mutation_job_rule (
            job_id INTEGER NOT NULL,
            rule_type TEXT NOT NULL CHECK(rule_type IN ('folder', 'keyword')),
            rule_id INTEGER NOT NULL,
            rule_version TEXT NOT NULL,
            PRIMARY KEY(job_id, rule_type, rule_id),
            FOREIGN KEY(job_id) REFERENCES history_mutation_job(id) ON DELETE CASCADE
        );
        """
    )


MIGRATIONS: dict[int, Migration] = {
    4: migrate_4_to_5,
    5: migrate_5_to_6,
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
    "migrate_schema",
]
