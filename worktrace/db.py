from __future__ import annotations

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
    db_path = configure_database(path)
    schema_path = Path(__file__).with_name("schema.sql")
    with get_connection() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        migrate_schema(conn)
        seed_defaults(conn)
    logging.info("database initialized")


def migrate_schema(conn: sqlite3.Connection) -> None:
    _drop_manual_project_session_schema(conn)


def _drop_manual_project_session_schema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS manual_project_session_activity")
    conn.execute("DROP TABLE IF EXISTS manual_project_session")


def seed_defaults(conn: sqlite3.Connection) -> None:
    ts = now_str()
    defaults = {
        "poll_interval_seconds": "3",
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
        "DELETE FROM settings WHERE key IN ('min_activity_seconds', 'min_history_seconds', 'min_idle_segment_seconds', 'idle_threshold_minutes')"
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
    excluded = conn.execute("SELECT id FROM project WHERE name = ?", (EXCLUDED_PROJECT,)).fetchone()
    if excluded:
        conn.execute(
            """
            DELETE FROM project_rule
            WHERE project_id = ?
              AND rule_type = 'keyword'
              AND created_by = 'system'
              AND pattern IN ('微信', '银行', '密码', '个人')
            """,
            (excluded["id"],),
        )


def reset_database() -> None:
    with get_connection() as conn:
        drop_all_tables(conn)
        schema_path = Path(__file__).with_name("schema.sql")
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        seed_defaults(conn)


def drop_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS activity_project_assignment;
        DROP TABLE IF EXISTS manual_project_session_activity;
        DROP TABLE IF EXISTS manual_project_session;
        DROP TABLE IF EXISTS activity_log;
        DROP TABLE IF EXISTS session_boundary;
        DROP TABLE IF EXISTS folder_project_rule;
        DROP TABLE IF EXISTS project_rule;
        DROP TABLE IF EXISTS project;
        DROP TABLE IF EXISTS settings;
        """
    )
