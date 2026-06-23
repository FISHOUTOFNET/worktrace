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
    with get_connection() as conn:
        conn.executescript(read_schema_sql())
        migrate_schema(conn)
        seed_defaults(conn)
        _write_schema_version(conn)
    logging.info("database initialized")


def _write_schema_version(conn: sqlite3.Connection) -> None:
    ts = now_str()
    conn.execute(
        """
        INSERT INTO settings(key, value, updated_at)
        VALUES ('schema_version', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (str(CURRENT_SCHEMA_VERSION), ts),
    )


def _read_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (ValueError, TypeError):
        return 0


def migrate_schema(conn: sqlite3.Connection) -> None:
    version = _read_schema_version(conn)
    if version >= CURRENT_SCHEMA_VERSION:
        return
    _drop_manual_project_session_schema(conn)
    _migrate_add_missing_columns(conn)
    _migrate_rebuild_tables_if_needed(conn)
    _migrate_create_activity_resource(conn)
    _write_schema_version(conn)


def _drop_manual_project_session_schema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS manual_project_session_activity")
    conn.execute("DROP TABLE IF EXISTS manual_project_session")


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _get_table_sql(conn: sqlite3.Connection, table_name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row["sql"] if row else None


# Columns that may be missing from older database schemas.
# Each entry: table_name -> list of (column_name, full_column_definition_for_ALTER)
_MISSING_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "activity_log": [
        ("file_path_hint", "TEXT"),
        ("auto_classified", "INTEGER NOT NULL DEFAULT 0"),
        ("manual_override", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "project": [
        ("created_by", "TEXT NOT NULL DEFAULT 'user'"),
        ("enabled", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "activity_project_assignment": [
        ("suggested_project_name", "TEXT"),
    ],
}


def _migrate_add_missing_columns(conn: sqlite3.Connection) -> None:
    for table_name, columns in _MISSING_COLUMNS.items():
        try:
            existing = _get_table_columns(conn, table_name)
        except Exception:
            continue
        for col_name, col_def in columns:
            if col_name not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
                    logging.info("migrated: added column %s.%s", table_name, col_name)
                except Exception:
                    logging.warning("failed to add column %s.%s", table_name, col_name, exc_info=True)


def _migrate_create_activity_resource(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'activity_resource'"
    ).fetchone()
    if existing:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_resource (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL,
            resource_kind TEXT NOT NULL CHECK (
                resource_kind IN (
                    'local_file',
                    'office_document',
                    'email',
                    'browser_tab',
                    'ide_file',
                    'app',
                    'system',
                    'unknown'
                )
            ),
            resource_subtype TEXT NOT NULL,
            display_name TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            is_anchor INTEGER NOT NULL DEFAULT 0,
            confidence INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL,
            app_name TEXT NOT NULL,
            process_name TEXT NOT NULL,
            window_title TEXT NOT NULL,
            path_hint TEXT,
            path_key TEXT,
            uri_scheme TEXT,
            uri_host TEXT,
            uri_hint TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (activity_id) REFERENCES activity_log(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_resource_activity "
        "ON activity_resource(activity_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_resource_identity "
        "ON activity_resource(identity_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_resource_kind "
        "ON activity_resource(resource_kind, resource_subtype)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_resource_path "
        "ON activity_resource(path_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_resource_host "
        "ON activity_resource(uri_host)"
    )
    logging.info("migrated: created activity_resource table and indexes")


def _migrate_rebuild_tables_if_needed(conn: sqlite3.Connection) -> None:
    """Rebuild tables whose CHECK constraints differ from the current schema.

    Uses safe rebuild: create new table, copy intersection columns, drop old,
    rename.
    """
    _maybe_rebuild_activity_log(conn)
    _maybe_rebuild_activity_project_assignment(conn)
    _maybe_rebuild_project_rule(conn)


def _rebuild_table(
    conn: sqlite3.Connection,
    table_name: str,
    new_ddl: str,
    copy_columns: list[str],
) -> bool:
    """Safely rebuild a table with a new DDL.

    1. Create temp table with new DDL.
    2. Copy data for intersection columns.
    3. Drop old table.
    4. Rename temp to original name.
    """
    temp_name = f"_temp_migrate_{table_name}"
    try:
        conn.execute(new_ddl.replace(f"CREATE TABLE IF NOT EXISTS {table_name}", f"CREATE TABLE {temp_name}", 1))
    except Exception:
        logging.warning("failed to create temp table for %s rebuild", table_name, exc_info=True)
        return False

    cols_str = ", ".join(copy_columns)
    try:
        conn.execute(f"INSERT INTO {temp_name} ({cols_str}) SELECT {cols_str} FROM {table_name}")
    except Exception:
        logging.warning("failed to copy data during %s rebuild", table_name, exc_info=True)
        conn.execute(f"DROP TABLE IF EXISTS {temp_name}")
        return False

    conn.execute(f"DROP TABLE {table_name}")
    conn.execute(f"ALTER TABLE {temp_name} RENAME TO {table_name}")
    logging.info("migrated: rebuilt table %s", table_name)
    return True


_ACTIVITY_LOG_COLUMNS = [
    "id", "start_time", "end_time", "duration_seconds",
    "app_name", "process_name", "window_title", "file_path_hint",
    "status", "source", "is_deleted", "is_hidden",
    "auto_classified", "manual_override", "project_id", "note",
    "created_at", "updated_at",
]


def _maybe_rebuild_activity_log(conn: sqlite3.Connection) -> None:
    sql = _get_table_sql(conn, "activity_log")
    if sql is None:
        return
    # Check if CHECK constraints are up to date
    needs_rebuild = False
    if "excluded" not in sql:
        needs_rebuild = True
    if "auto" not in sql or "manual" not in sql or "system" not in sql:
        needs_rebuild = True
    if not needs_rebuild:
        return

    existing_cols = _get_table_columns(conn, "activity_log")
    copy_cols = [c for c in _ACTIVITY_LOG_COLUMNS if c in existing_cols]
    new_ddl = (
        "CREATE TABLE IF NOT EXISTS activity_log (\n"
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    start_time TEXT NOT NULL,\n"
        "    end_time TEXT,\n"
        "    duration_seconds INTEGER,\n"
        "    app_name TEXT NOT NULL,\n"
        "    process_name TEXT NOT NULL,\n"
        "    window_title TEXT NOT NULL,\n"
        "    file_path_hint TEXT,\n"
        "    status TEXT NOT NULL CHECK (\n"
        "        status IN ('normal', 'idle', 'paused', 'excluded', 'error')\n"
        "    ),\n"
        "    source TEXT NOT NULL CHECK (\n"
        "        source IN ('auto', 'manual', 'system')\n"
        "    ),\n"
        "    is_deleted INTEGER NOT NULL DEFAULT 0,\n"
        "    is_hidden INTEGER NOT NULL DEFAULT 0,\n"
        "    auto_classified INTEGER NOT NULL DEFAULT 0,\n"
        "    manual_override INTEGER NOT NULL DEFAULT 0,\n"
        "    project_id INTEGER,\n"
        "    note TEXT,\n"
        "    created_at TEXT NOT NULL,\n"
        "    updated_at TEXT NOT NULL,\n"
        "    FOREIGN KEY (project_id) REFERENCES project(id)\n"
        ")"
    )
    _rebuild_table(conn, "activity_log", new_ddl, copy_cols)
    # Re-create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(start_time, end_time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_status ON activity_log(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_project ON activity_log(project_id)")


_ACTIVITY_PROJECT_ASSIGNMENT_COLUMNS = [
    "activity_id", "project_id", "confidence", "source",
    "is_manual", "suggested_project_name", "created_at", "updated_at",
]


def _maybe_rebuild_activity_project_assignment(conn: sqlite3.Connection) -> None:
    sql = _get_table_sql(conn, "activity_project_assignment")
    if sql is None:
        return
    needs_rebuild = False
    for keyword in ("midnight_anchor", "keyword_rule", "clipboard_transition_context", "suggested_project_name", "folder_rule"):
        if keyword not in sql:
            needs_rebuild = True
            break
    if not needs_rebuild:
        return

    existing_cols = _get_table_columns(conn, "activity_project_assignment")
    copy_cols = [c for c in _ACTIVITY_PROJECT_ASSIGNMENT_COLUMNS if c in existing_cols]
    new_ddl = (
        "CREATE TABLE IF NOT EXISTS activity_project_assignment (\n"
        "    activity_id INTEGER PRIMARY KEY,\n"
        "    project_id INTEGER,\n"
        "    confidence INTEGER NOT NULL DEFAULT 0,\n"
        "    source TEXT NOT NULL CHECK (\n"
        "        source IN (\n"
        "            'manual',\n"
        "            'keyword_rule',\n"
        "            'anchor_context',\n"
        "            'clipboard_transition_context',\n"
        "            'folder_rule',\n"
        "            'midnight_anchor',\n"
        "            'suggested_project_name',\n"
        "            'uncategorized'\n"
        "        )\n"
        "    ),\n"
        "    is_manual INTEGER NOT NULL DEFAULT 0,\n"
        "    suggested_project_name TEXT,\n"
        "    created_at TEXT NOT NULL,\n"
        "    updated_at TEXT NOT NULL,\n"
        "    FOREIGN KEY (activity_id) REFERENCES activity_log(id),\n"
        "    FOREIGN KEY (project_id) REFERENCES project(id)\n"
        ")"
    )
    _rebuild_table(conn, "activity_project_assignment", new_ddl, copy_cols)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assignment_project ON activity_project_assignment(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assignment_source_manual ON activity_project_assignment(source, is_manual)")


_PROJECT_RULE_COLUMNS = [
    "id", "project_id", "rule_type", "pattern", "enabled",
    "created_by", "created_at", "updated_at",
]


def _maybe_rebuild_project_rule(conn: sqlite3.Connection) -> None:
    sql = _get_table_sql(conn, "project_rule")
    if sql is None:
        return
    if "keyword" in sql:
        return

    existing_cols = _get_table_columns(conn, "project_rule")
    copy_cols = [c for c in _PROJECT_RULE_COLUMNS if c in existing_cols]
    new_ddl = (
        "CREATE TABLE IF NOT EXISTS project_rule (\n"
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    project_id INTEGER NOT NULL,\n"
        "    rule_type TEXT NOT NULL CHECK (\n"
        "        rule_type IN ('keyword')\n"
        "    ),\n"
        "    pattern TEXT NOT NULL,\n"
        "    enabled INTEGER NOT NULL DEFAULT 1,\n"
        "    created_by TEXT NOT NULL DEFAULT 'user' CHECK (\n"
        "        created_by IN ('system', 'user')\n"
        "    ),\n"
        "    created_at TEXT NOT NULL,\n"
        "    updated_at TEXT NOT NULL,\n"
        "    FOREIGN KEY (project_id) REFERENCES project(id)\n"
        ")"
    )
    _rebuild_table(conn, "project_rule", new_ddl, copy_cols)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_rule_pattern ON project_rule(pattern)")


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
        "clipboard_capture_enabled": "false",
        "email_metadata_capture_enabled": "false",
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
        conn.executescript(read_schema_sql())
        seed_defaults(conn)
        _write_schema_version(conn)


def drop_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS activity_resource;
        DROP TABLE IF EXISTS folder_rule_file_index;
        DROP TABLE IF EXISTS folder_rule_index_state;
        DROP TABLE IF EXISTS project_session_note;
        DROP TABLE IF EXISTS activity_clipboard_event;
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
