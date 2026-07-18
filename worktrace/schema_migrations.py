"""Sequential, explicit WorkTrace schema migrations.

Migrations only cover published supported versions. They run before background
workers start and must be deterministic.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

_CURRENT_SNAPSHOT_KEY = "current_activity_snapshot"
_PENDING_SECONDS_KEY = "pending_short_seconds"
_PENDING_PROVENANCE_KEY = "pending_short_carry_provenance"

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

    # Rebuild both folder-index tables rather than appending columns. This keeps
    # upgraded databases byte-for-byte structurally equivalent to fresh v6
    # databases, which is required by WorkTrace's schema fingerprint contract.
    conn.execute(
        "ALTER TABLE folder_rule_index_state RENAME TO folder_rule_index_state_v5"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS folder_rule_index_state (
            folder_rule_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'indexing', 'ready', 'stale', 'error')
            ),
            valid_from TEXT,
            active_generation INTEGER,
            building_generation INTEGER,
            build_status TEXT CHECK (
                build_status IS NULL OR build_status IN ('pending', 'indexing', 'ready', 'stale', 'error')
            ),
            last_error TEXT,
            last_indexed_at TEXT,
            last_checked_at TEXT,
            file_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            refresh_requested INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (folder_rule_id) REFERENCES folder_project_rule(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        INSERT INTO folder_rule_index_state(
            folder_rule_id, status, valid_from, active_generation,
            building_generation, build_status, last_error, last_indexed_at,
            last_checked_at, file_count, error_message, refresh_requested,
            created_at, updated_at
        )
        SELECT
            state.folder_rule_id,
            CASE WHEN state.status = 'indexing' THEN 'pending' ELSE state.status END,
            CASE WHEN state.status = 'indexing' THEN NULL ELSE state.valid_from END,
            CASE
                WHEN state.status IN ('ready', 'stale')
                 AND EXISTS (
                    SELECT 1 FROM folder_rule_file_index idx
                    WHERE idx.folder_rule_id = state.folder_rule_id
                 )
                THEN 1 ELSE NULL
            END,
            NULL,
            CASE WHEN state.status = 'indexing' THEN 'pending' ELSE state.status END,
            state.error_message,
            state.last_indexed_at,
            state.last_checked_at,
            CASE WHEN state.status = 'indexing' THEN 0 ELSE state.file_count END,
            CASE WHEN state.status = 'indexing' THEN NULL ELSE state.error_message END,
            CASE WHEN state.status = 'indexing' THEN 1 ELSE state.refresh_requested END,
            state.created_at,
            state.updated_at
        FROM folder_rule_index_state_v5 state
        """
    )
    conn.execute("DROP TABLE folder_rule_index_state_v5")

    conn.execute(
        "ALTER TABLE folder_rule_file_index RENAME TO folder_rule_file_index_v5"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS folder_rule_file_index (
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

    # sqlite3.Connection.executescript() performs an implicit COMMIT and would
    # destroy migrate_schema()'s savepoint. Keep every DDL statement inside the
    # caller-controlled migration transaction.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history_mutation_job (
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
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history_mutation_job_rule (
            job_id INTEGER NOT NULL,
            rule_type TEXT NOT NULL CHECK(rule_type IN ('folder', 'keyword')),
            rule_id INTEGER NOT NULL,
            rule_version TEXT NOT NULL,
            PRIMARY KEY(job_id, rule_type, rule_id),
            FOREIGN KEY(job_id) REFERENCES history_mutation_job(id) ON DELETE CASCADE
        )
        """
    )


def migrate_6_to_7(conn: sqlite3.Connection) -> None:
    """Add the durable structural generation used by page refresh contracts."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_structure_revision_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            generation INTEGER NOT NULL CHECK(generation >= 0)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO report_structure_revision_state(singleton_id, generation)
        VALUES (1, 0)
        ON CONFLICT(singleton_id) DO NOTHING
        """
    )


def migrate_7_to_8(conn: sqlite3.Connection) -> None:
    """Replace the report-only revision row with named durable generations."""

    old_row = conn.execute(
        """
        SELECT generation
        FROM report_structure_revision_state
        WHERE singleton_id = 1
        """
    ).fetchone()
    report_generation = int(old_row[0] if old_row is not None else 0)
    if report_generation < 0:
        raise ValueError("database_schema_incompatible")

    conn.execute(
        """
        CREATE TABLE data_generation_state (
            namespace TEXT PRIMARY KEY CHECK(length(trim(namespace)) > 0),
            generation INTEGER NOT NULL CHECK(generation >= 0)
        )
        """
    )
    conn.executemany(
        "INSERT INTO data_generation_state(namespace, generation) VALUES (?, ?)",
        [
            ("report_structure", report_generation),
            ("classification_catalog", 0),
            ("settings", 0),
            ("privacy_catalog", 0),
            ("database_replacement", 0),
        ],
    )
    conn.execute("DROP TABLE report_structure_revision_state")


def migrate_8_to_9(conn: sqlite3.Connection) -> None:
    """Move activity-resource repair progress out of business settings."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_resource_repair_job (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            policy_version INTEGER NOT NULL CHECK(policy_version > 0),
            status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
            cursor_activity_id INTEGER NOT NULL DEFAULT 0 CHECK(cursor_activity_id >= 0),
            processed_count INTEGER NOT NULL DEFAULT 0 CHECK(processed_count >= 0),
            repaired_count INTEGER NOT NULL DEFAULT 0 CHECK(repaired_count >= 0),
            failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
            unknown_count INTEGER NOT NULL DEFAULT 0 CHECK(unknown_count >= 0),
            last_error TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        ("maintenance.activity_resource_repair.v1",),
    ).fetchone()
    if row is not None:
        try:
            raw = json.loads(str(row[0] or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict) and int(raw.get("policy_version") or 0) == 1:
            status = str(raw.get("status") or "pending")
            if status not in {"pending", "running", "completed", "failed"}:
                status = "pending"
            conn.execute(
                """
                INSERT INTO activity_resource_repair_job(
                    singleton_id, policy_version, status, cursor_activity_id,
                    processed_count, repaired_count, failed_count, unknown_count,
                    last_error, started_at, completed_at, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    status,
                    max(0, int(raw.get("cursor_activity_id") or 0)),
                    max(0, int(raw.get("scanned_count") or 0)),
                    max(0, int(raw.get("repaired_count") or 0)),
                    max(0, int(raw.get("error_count") or 0)),
                    max(0, int(raw.get("unknown_count") or 0)),
                    str(raw.get("last_error") or ""),
                    str(raw.get("started_at") or ""),
                    str(raw.get("completed_at") or ""),
                    str(raw.get("updated_at") or ""),
                ),
            )
        conn.execute(
            "DELETE FROM settings WHERE key = ?",
            ("maintenance.activity_resource_repair.v1",),
        )


def migrate_9_to_10(conn: sqlite3.Connection) -> None:
    """Normalize legacy reserved rows before database ownership constraints."""

    conn.execute(
        """
        UPDATE project
        SET created_by = 'system', updated_at = datetime('now', 'localtime')
        WHERE name IN ('未归类', '排除规则')
          AND created_by <> 'system'
        """
    )


def migrate_10_to_11(conn: sqlite3.Connection) -> None:
    """Persist every eligible closed-activity inference request durably."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_inference_job (
            activity_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'running', 'failed')
            ),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            next_attempt_at TEXT,
            last_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(activity_id) REFERENCES activity_log(id) ON DELETE CASCADE
        )
        """
    )
    now = conn.execute("SELECT datetime('now', 'localtime')").fetchone()[0]
    conn.execute(
        """
        INSERT OR IGNORE INTO activity_inference_job(
            activity_id, status, attempt_count, next_attempt_at,
            last_error_code, created_at, updated_at
        )
        SELECT
            activity.id, 'pending', 0, NULL, NULL, ?, ?
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
                    AND assignment.source IN ('uncategorized', 'suggested_project_name')
                )
          )
        """,
        (str(now), str(now)),
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
