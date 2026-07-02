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
        # Section 八: poll interval default is 1 second. WorkTrace is a
        # local automatic time-tracking tool; the immediacy of current
        # activity change perception takes priority over the minor polling
        # overhead. No system-level foreground event hook is used.
        "poll_interval_seconds": "1",
        "idle_threshold_seconds": str(DEFAULT_IDLE_THRESHOLD_SECONDS),
        "current_activity_snapshot": "",
        "pending_short_seconds": "0",
        "collector_status": "stopped",
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
        INSERT INTO project(name, description, is_archived, enabled, created_by, created_at, updated_at)
        VALUES (?, '', 0, 1, 'system', ?, ?)
        ON CONFLICT(name) DO NOTHING
        """,
        (UNCATEGORIZED_PROJECT, ts, ts),
    )
    conn.execute(
        """
        INSERT INTO project(name, description, is_archived, enabled, created_by, created_at, updated_at)
        VALUES (?, '命中后匿名记录', 0, 0, 'system', ?, ?)
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
    """Run idempotent schema migrations for older databases.

    ``CREATE TABLE IF NOT EXISTS`` in ``schema.sql`` does not add new
    columns to existing tables. This function checks for and adds any
    columns introduced after the initial table creation. Each migration
    is idempotent: it uses ``PRAGMA table_info`` to check whether the
    column already exists before running ``ALTER TABLE``.
    """
    ensure_project_session_note_adjusted_duration_column(conn)


def ensure_project_session_note_adjusted_duration_column(conn: sqlite3.Connection) -> None:
    """Add ``adjusted_duration_seconds`` to ``project_session_note`` if missing.

    Idempotent: checks ``PRAGMA table_info(project_session_note)`` before
    running ``ALTER TABLE``. Safe to call on both new and already-migrated
    databases.
    """
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(project_session_note)").fetchall()}
    if "adjusted_duration_seconds" not in columns:
        conn.execute(
            "ALTER TABLE project_session_note ADD COLUMN adjusted_duration_seconds INTEGER"
        )


def drop_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS activity_resource;
        DROP TABLE IF EXISTS folder_rule_file_index;
        DROP TABLE IF EXISTS folder_rule_index_state;
        DROP TABLE IF EXISTS project_session_note;
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
