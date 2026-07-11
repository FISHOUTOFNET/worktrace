from __future__ import annotations

from importlib import resources
import json
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
    """Create tables, run idempotent migrations/post-indexes, then seed."""
    conn.executescript(read_schema_sql())
    ensure_schema_migrations(conn)
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


def ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    """Run idempotent schema migrations.

    ``CREATE TABLE IF NOT EXISTS`` in ``schema.sql`` does not add new
    columns to existing tables. This function checks for and adds any
    columns missing from existing tables. Each migration is idempotent:
    it uses ``PRAGMA table_info`` to check whether the column already
    exists before running ``ALTER TABLE``.
    """
    ensure_project_language_column(conn)
    ensure_project_deleted_column(conn)
    ensure_assignment_rule_origin_columns(conn)
    ensure_report_session_operation_tables(conn)
    ensure_current_indexes(conn)


def ensure_current_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(read_schema_indexes_sql())


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


def ensure_project_deleted_column(conn: sqlite3.Connection) -> None:
    """Add soft-delete lifecycle state to existing projects."""
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(project)").fetchall()}
    if "is_deleted" not in columns:
        conn.execute("ALTER TABLE project ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")


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


def ensure_report_session_operation_tables(conn: sqlite3.Connection) -> None:
    """Create report-session operation tables for databases predating them."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS report_session_operation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            operation_type TEXT NOT NULL CHECK(operation_type IN ('edit_session', 'hide_session', 'merge_sessions', 'copy_session', 'hide_activity')),
            base_instance_key TEXT NOT NULL,
            target_instance_key TEXT,
            direction TEXT CHECK(direction IS NULL OR direction IN ('previous', 'next')),
            operation_group_key TEXT,
            replay_order INTEGER NOT NULL DEFAULT 0,
            match_state TEXT NOT NULL DEFAULT 'active' CHECK(match_state IN ('active', 'conflict', 'orphaned', 'superseded')),
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_session_operation_member (
            operation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('source', 'target', 'origin', 'copy_origin', 'hidden_activity', 'edit_target')),
            activity_id INTEGER NOT NULL,
            report_date TEXT NOT NULL,
            slice_start_time TEXT NOT NULL,
            slice_end_time TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(operation_id, role, activity_id, report_date, slice_start_time),
            FOREIGN KEY(operation_id) REFERENCES report_session_operation(id) ON DELETE CASCADE,
            FOREIGN KEY(activity_id) REFERENCES activity_log(id)
        );
        """
    )
    _rebuild_operation_tables_if_legacy(conn)
    _migrate_project_session_overrides_to_operations(conn)
    _drop_legacy_project_session_override_tables(conn)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone())


def _table_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    if not _table_exists(conn, name):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({name})").fetchall()}


def _rebuild_operation_tables_if_legacy(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "report_session_operation")
    sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'report_session_operation'"
    ).fetchone()
    sql = str(sql_row["sql"] or "") if sql_row else ""
    member_sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'report_session_operation_member'"
    ).fetchone()
    member_sql = str(member_sql_row["sql"] or "") if member_sql_row else ""
    needs_rebuild = (
        "replay_order" not in columns
        or "edit_session" not in sql
        or "edit_target" not in member_sql
        or "slice_end_time" in member_sql.partition("PRIMARY KEY")[2].partition(")")[0]
    )
    if not needs_rebuild:
        _backfill_replay_order(conn)
        return
    conn.executescript(
        """
        ALTER TABLE report_session_operation RENAME TO report_session_operation_legacy;
        ALTER TABLE report_session_operation_member RENAME TO report_session_operation_member_legacy;
        CREATE TABLE report_session_operation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            operation_type TEXT NOT NULL CHECK(operation_type IN ('edit_session', 'hide_session', 'merge_sessions', 'copy_session', 'hide_activity')),
            base_instance_key TEXT NOT NULL,
            target_instance_key TEXT,
            direction TEXT CHECK(direction IS NULL OR direction IN ('previous', 'next')),
            operation_group_key TEXT,
            replay_order INTEGER NOT NULL DEFAULT 0,
            match_state TEXT NOT NULL DEFAULT 'active' CHECK(match_state IN ('active', 'conflict', 'orphaned', 'superseded')),
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE report_session_operation_member (
            operation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('source', 'target', 'origin', 'copy_origin', 'hidden_activity', 'edit_target')),
            activity_id INTEGER NOT NULL,
            report_date TEXT NOT NULL,
            slice_start_time TEXT NOT NULL,
            slice_end_time TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(operation_id, role, activity_id, report_date, slice_start_time),
            FOREIGN KEY(operation_id) REFERENCES report_session_operation(id) ON DELETE CASCADE,
            FOREIGN KEY(activity_id) REFERENCES activity_log(id)
        );
        INSERT INTO report_session_operation(
            id, report_date, operation_type, base_instance_key, target_instance_key,
            direction, operation_group_key, replay_order, match_state, payload_json, created_at, updated_at
        )
        SELECT id, report_date, operation_type, base_instance_key, target_instance_key,
               direction, operation_group_key, 0, match_state, payload_json, created_at, updated_at
        FROM report_session_operation_legacy;
        INSERT OR IGNORE INTO report_session_operation_member(
            operation_id, role, activity_id, report_date, slice_start_time, slice_end_time, display_order
        )
        SELECT operation_id, role, activity_id, report_date, slice_start_time, slice_end_time, display_order
        FROM report_session_operation_member_legacy;
        DROP TABLE report_session_operation_member_legacy;
        DROP TABLE report_session_operation_legacy;
        """
    )
    _backfill_replay_order(conn)


def _backfill_replay_order(conn: sqlite3.Connection) -> None:
    dates = [
        str(row["report_date"])
        for row in conn.execute(
            "SELECT DISTINCT report_date FROM report_session_operation WHERE replay_order = 0 ORDER BY report_date"
        ).fetchall()
    ]
    for report_date in dates:
        rows = conn.execute(
            "SELECT id FROM report_session_operation WHERE report_date = ? ORDER BY id",
            (report_date,),
        ).fetchall()
        for order, row in enumerate(rows, 1):
            conn.execute(
                "UPDATE report_session_operation SET replay_order = ? WHERE id = ? AND replay_order = 0",
                (order, int(row["id"])),
            )


def _migrate_project_session_overrides_to_operations(conn: sqlite3.Connection) -> None:
    if not (_table_exists(conn, "project_session_override") and _table_exists(conn, "project_session_override_member")):
        return
    existing_marker = conn.execute(
        """
        SELECT 1 FROM report_session_operation
        WHERE operation_type = 'edit_session'
          AND json_extract(payload_json, '$.migration_source') = 'project_session_override'
        LIMIT 1
        """
    ).fetchone()
    if existing_marker:
        return
    from .services.report_projection_identity import base_projection_key, member_set_hash

    rows = conn.execute(
        """
        SELECT o.*, p.name AS project_name, p.description AS project_description,
               COALESCE(p.is_deleted, 0) AS project_is_deleted,
               COALESCE(p.is_archived, 0) AS project_is_archived
        FROM project_session_override o
        LEFT JOIN project p ON p.id = o.project_id
        ORDER BY o.report_date, o.updated_at, o.id
        """
    ).fetchall()
    active_by_key: dict[tuple[str, str], int] = {}
    member_order = "display_order, activity_id" if "display_order" in _table_columns(conn, "project_session_override_member") else "activity_id"
    for row in rows:
        members = [dict(member) for member in conn.execute(
            f"""
            SELECT activity_id, report_date, slice_start_time, slice_end_time
            FROM project_session_override_member
            WHERE override_id = ?
            ORDER BY {member_order}
            """,
            (int(row["id"]),),
        ).fetchall()]
        stable_hash = member_set_hash(str(row["report_date"]), members)
        key = (str(row["report_date"]), stable_hash)
        if str(row["match_state"]) == "active":
            active_by_key[key] = int(row["id"])
    for row in rows:
        members = [dict(member) for member in conn.execute(
            f"""
            SELECT activity_id, report_date, slice_start_time, slice_end_time
            FROM project_session_override_member
            WHERE override_id = ?
            ORDER BY {member_order}
            """,
            (int(row["id"]),),
        ).fetchall()]
        if not members:
            match_state = "orphaned"
        else:
            stable_hash = member_set_hash(str(row["report_date"]), members)
            match_state = str(row["match_state"] or "active")
            if match_state == "active" and active_by_key.get((str(row["report_date"]), stable_hash)) != int(row["id"]):
                match_state = "superseded"
        payload = {
            "payload_version": 1,
            "migration_source": "project_session_override",
            "legacy_override_id": int(row["id"]),
        }
        if row["project_id"] is not None:
            payload["project"] = {
                "mode": "set",
                "project_id": int(row["project_id"]),
                "project_name": str(row["project_name"] or ""),
                "project_description": str(row["project_description"] or ""),
                "project_is_deleted": bool(int(row["project_is_deleted"] or 0)),
                "project_is_archived": bool(int(row["project_is_archived"] or 0)),
            }
        if row["adjusted_duration_seconds"] is not None:
            payload["duration"] = {"mode": "set", "value": int(row["adjusted_duration_seconds"])}
        if str(row["note"] or ""):
            payload["note"] = {"mode": "set", "value": str(row["note"] or "")}
        if not any(key in payload for key in ("project", "duration", "note")):
            continue
        report_date = str(row["report_date"])
        conn.execute(
            "UPDATE report_session_operation SET replay_order = replay_order + 1000000 WHERE report_date = ?",
            (report_date,),
        )
        cur = conn.execute(
            """
            INSERT INTO report_session_operation(
                report_date, operation_type, base_instance_key, target_instance_key,
                direction, operation_group_key, replay_order, match_state, payload_json,
                created_at, updated_at
            ) VALUES (?, 'edit_session', ?, NULL, NULL, NULL, ?, ?, ?, ?, ?)
            """,
            (
                report_date,
                base_projection_key(report_date, members),
                int(row["id"]),
                match_state,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                str(row["created_at"]),
                str(row["updated_at"]),
            ),
        )
        operation_id = int(cur.lastrowid)
        for order, member in enumerate(members):
            conn.execute(
                """
                INSERT OR IGNORE INTO report_session_operation_member(
                    operation_id, role, activity_id, report_date, slice_start_time, slice_end_time, display_order
                ) VALUES (?, 'edit_target', ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    int(member["activity_id"]),
                    str(member["report_date"]),
                    str(member["slice_start_time"]),
                    str(member["slice_end_time"]),
                    order,
                ),
            )
    _normalize_replay_order(conn)


def _normalize_replay_order(conn: sqlite3.Connection) -> None:
    dates = [
        str(row["report_date"])
        for row in conn.execute("SELECT DISTINCT report_date FROM report_session_operation ORDER BY report_date").fetchall()
    ]
    for report_date in dates:
        rows = conn.execute(
            "SELECT id FROM report_session_operation WHERE report_date = ? ORDER BY replay_order, id",
            (report_date,),
        ).fetchall()
        for order, row in enumerate(rows, 1):
            conn.execute("UPDATE report_session_operation SET replay_order = ? WHERE id = ?", (order, int(row["id"])))


def _drop_legacy_project_session_override_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS project_session_override_member;
        DROP TABLE IF EXISTS project_session_override;
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
