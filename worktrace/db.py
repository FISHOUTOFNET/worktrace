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

CURRENT_SCHEMA_VERSION = 3


def read_schema_sql() -> str:
    return resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")


def read_schema_indexes_sql() -> str:
    return resources.files(__package__).joinpath("schema_indexes.sql").read_text(encoding="utf-8")


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
    apply_connection_pragmas(conn)
    return conn


def apply_connection_pragmas(conn: sqlite3.Connection) -> None:
    """Apply settings which are local to this connection.

    WAL is a database property.  Setting it while opening every short-lived
    reader can contend with the collector, so it is established only at
    database lifecycle boundaries below.
    """
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")


def ensure_wal(conn: sqlite3.Connection) -> None:
    """Establish the database-wide WAL contract at an explicit lifecycle edge."""
    conn.execute("PRAGMA journal_mode = WAL;")


def dict_rows(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def initialize_database(path: str | Path | None = None) -> None:
    configure_database(path)
    with get_connection() as conn:
        ensure_wal(conn)
        apply_current_schema(conn)
    logging.info("database initialized")


def apply_current_schema(conn: sqlite3.Connection) -> None:
    """Create the current schema or reject incompatible existing data."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    has_user_tables = _database_has_user_tables(conn)
    if has_user_tables and version != CURRENT_SCHEMA_VERSION:
        raise ValueError("database_schema_incompatible")
    if not has_user_tables:
        conn.executescript(read_schema_sql())
        ensure_current_indexes(conn)
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
    else:
        conn.executescript(read_schema_sql())
        ensure_current_indexes(conn)
    seed_defaults(conn)


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
        ensure_wal(conn)
        drop_all_tables(conn)
        apply_current_schema(conn)


def _database_has_user_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def ensure_current_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(read_schema_indexes_sql())


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone())


def _table_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    if not _table_exists(conn, name):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({name})").fetchall()}


def drop_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS activity_resource;
        DROP TABLE IF EXISTS folder_rule_file_index;
        DROP TABLE IF EXISTS folder_rule_index_state;
        DROP TABLE IF EXISTS report_session_operation_supersession;
        DROP TABLE IF EXISTS report_session_operation_dependency;
        DROP TABLE IF EXISTS report_session_operation_member;
        DROP TABLE IF EXISTS report_mutation_request;
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
