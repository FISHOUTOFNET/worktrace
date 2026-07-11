from __future__ import annotations

from importlib import resources
import logging
import sqlite3
from pathlib import Path
from typing import Iterable

from . import config
from .constants import (
    DEFAULT_CONTEXT_CARRY_MINUTES,
    DEFAULT_IDLE_THRESHOLD_SECONDS,
    EXCLUDED_PROJECT,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)


def read_schema_sql() -> str:
    return resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")


_db_path: Path | None = None


def now_str() -> str:
    from datetime import datetime

    return datetime.now().strftime(TIME_FORMAT)


def configure_database(path: str | Path | None = None) -> Path:
    global _db_path
    _db_path = Path(path) if path is not None else config.resolve_paths().db_path
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    return _db_path


def get_db_path() -> Path:
    global _db_path
    if _db_path is None:
        configure_database()
    assert _db_path is not None
    return _db_path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    return conn


def apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")


def dict_rows(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def initialize_database(path: str | Path | None = None) -> None:
    configure_database(path)
    with get_connection() as conn:
        conn.executescript(read_schema_sql())
        ensure_schema_migrations(conn)
        seed_defaults(conn)
    logging.info("database initialized")


def seed_defaults(conn: sqlite3.Connection) -> None:
    ts = now_str()
    defaults = {
        # Poll interval default is 1 second. WorkTrace is a local automatic
        # time-tracking tool; the immediacy of current activity change
        # perception takes priority over the minor polling overhead. No
        # system-level foreground event hook is used.
        "poll_interval_seconds": "1",
        "idle_threshold_seconds": str(DEFAULT_IDLE_THRESHOLD_SECONDS),
        "current_activity_snapshot": "",
        "pending_short_seconds": "0",
        "pending_short_carry_provenance": "",
        "collector_status": "stopped",
        "collector_health_state": "stopped",
        "collector_last_successful_observation_at": "",
        "collector_last_failure_at": "",
        "collector_consecutive_failures": "0",
        "collector_last_failure_phase": "",
        "collector_last_failure_kind": "",
        "collector_stall_threshold_seconds": "180",
        "clock_jump_threshold_seconds": "300",
        "last_collector_heartbeat": "",
        "last_shutdown_at": "",
        "first_run_notice_accepted": "false",
        "export_path": str(config.get_default_export_dir().resolve()),
        "ui_refresh_seconds": "10",
        "user_paused": "false",
        "context_carry_minutes": str(DEFAULT_CONTEXT_CARRY_MINUTES),
        "clipboard_capture_enabled": "false",
        "secure_import_in_progress": "false",
    }
    for key, value in defaults.items():
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, value, ts),
        )
    conn.execute(
        """
        INSERT INTO project(name, description, language, is_archived, enabled, created_by, created_at, updated_at)
        VALUES (?, '', '中文', 0, 1, 'system', ?, ?)
        ON CONFLICT(name) DO NOTHING
        """,
        (UNCATEGORIZED_PROJECT, ts, ts),
    )
    conn.execute(
        """
        INSERT INTO project(name, description, language, is_archived, enabled, created_by, created_at, updated_at)
        VALUES (?, '命中后匿名记录', '中文', 0, 0, 'system', ?, ?)
        ON CONFLICT(name) DO NOTHING
        """,
        (EXCLUDED_PROJECT, ts, ts),
    )


def reset_database() -> None:
    with get_connection() as conn:
        drop_all_tables(conn)
        conn.executescript(read_schema_sql())
        ensure_schema_migrations(conn)
        seed_defaults(conn)


def ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    """Run idempotent schema migrations.

    ``CREATE TABLE IF NOT EXISTS`` in ``schema.sql`` does not add new
    columns to existing tables. This function checks for and adds any
    columns missing from existing tables. Each migration is idempotent:
    it uses ``PRAGMA table_info`` to check whether the column already
    exists before running ``ALTER TABLE``.
    """
    ensure_project_language_column(conn)
    ensure_assignment_rule_origin_columns(conn)
    ensure_report_session_operation_tables(conn)


def ensure_project_language_column(conn: sqlite3.Connection) -> None:
    """Add ``language`` to ``project`` if missing.

    Idempotent: checks ``PRAGMA table_info(project)`` before running
    ``ALTER TABLE``. Existing projects receive the stable default ``中文``.
    """
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(project)").fetchall()}
    if "language" not in columns:
        conn.execute(
            "ALTER TABLE project ADD COLUMN language TEXT NOT NULL DEFAULT '中文'"
        )


def ensure_assignment_rule_origin_columns(conn: sqlite3.Connection) -> None:
    """Add direct-rule origin fields to existing assignment tables.

    There is deliberately no foreign key: keyword and folder rules live in
    separate tables, and a historical assignment may retain its origin after
    the rule itself is deleted.
    """
    columns = {str(row["name"]) for row in conn.execute(
        "PRAGMA table_info(activity_project_assignment)"
    ).fetchall()}
    if "source_rule_type" not in columns:
        conn.execute(
            "ALTER TABLE activity_project_assignment ADD COLUMN source_rule_type TEXT NULL"
        )
    if "source_rule_id" not in columns:
        conn.execute(
            "ALTER TABLE activity_project_assignment ADD COLUMN source_rule_id INTEGER NULL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_assignment_source_rule "
        "ON activity_project_assignment(source_rule_type, source_rule_id, is_manual)"
    )


def ensure_report_session_operation_tables(conn: sqlite3.Connection) -> None:
    """Create report-session operation tables for databases predating them."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS report_session_operation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            operation_type TEXT NOT NULL CHECK(operation_type IN ('hide_session', 'merge_sessions', 'copy_session', 'hide_activity')),
            base_instance_key TEXT NOT NULL,
            target_instance_key TEXT,
            direction TEXT CHECK(direction IS NULL OR direction IN ('previous', 'next')),
            operation_group_key TEXT,
            match_state TEXT NOT NULL DEFAULT 'active' CHECK(match_state IN ('active', 'conflict', 'orphaned', 'superseded')),
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_session_operation_member (
            operation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('source', 'target', 'origin', 'copy_origin', 'hidden_activity')),
            activity_id INTEGER NOT NULL,
            report_date TEXT NOT NULL,
            slice_start_time TEXT NOT NULL,
            slice_end_time TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(operation_id, role, activity_id, report_date, slice_start_time, slice_end_time),
            FOREIGN KEY(operation_id) REFERENCES report_session_operation(id) ON DELETE CASCADE,
            FOREIGN KEY(activity_id) REFERENCES activity_log(id)
        );
        CREATE INDEX IF NOT EXISTS idx_report_session_operation_date_state
        ON report_session_operation(report_date, match_state);
        CREATE INDEX IF NOT EXISTS idx_report_session_operation_instance
        ON report_session_operation(report_date, base_instance_key, match_state);
        CREATE INDEX IF NOT EXISTS idx_report_session_operation_group
        ON report_session_operation(operation_group_key, match_state);
        CREATE INDEX IF NOT EXISTS idx_report_session_operation_member_activity
        ON report_session_operation_member(activity_id, report_date);
        CREATE INDEX IF NOT EXISTS idx_report_session_operation_member_role
        ON report_session_operation_member(operation_id, role);
        """
    )


def drop_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS activity_resource;
        DROP TABLE IF EXISTS folder_rule_file_index;
        DROP TABLE IF EXISTS folder_rule_index_state;
        DROP TABLE IF EXISTS project_session_override_member;
        DROP TABLE IF EXISTS project_session_override;
        DROP TABLE IF EXISTS report_session_operation_member;
        DROP TABLE IF EXISTS report_session_operation;
        DROP TABLE IF EXISTS activity_clipboard_event;
        DROP TABLE IF EXISTS activity_project_assignment;
        DROP TABLE IF EXISTS activity_log;
        DROP TABLE IF EXISTS session_boundary;
        DROP TABLE IF EXISTS folder_project_rule;
        DROP TABLE IF EXISTS project_rule;
        DROP TABLE IF EXISTS project;
        DROP TABLE IF EXISTS settings;
        """
    )
