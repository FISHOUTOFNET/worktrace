"""Tests for current schema initialization, migration and reset."""
from __future__ import annotations

import sqlite3

import pytest

from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT

pytestmark = [pytest.mark.db, pytest.mark.contract]

EXPECTED_TABLES = {
    "project",
    "activity_log",
    "settings",
    "session_boundary",
    "folder_project_rule",
    "folder_rule_index_state",
    "folder_rule_file_index",
    "project_rule",
    "activity_project_assignment",
    "activity_clipboard_event",
    "report_session_operation",
    "report_session_operation_member",
    "activity_resource",
}

EXPECTED_DEFAULT_SETTINGS = {
    "poll_interval_seconds",
    "idle_threshold_seconds",
    "collector_status",
    "last_collector_heartbeat",
    "last_shutdown_at",
    "first_run_notice_accepted",
    "export_path",
    "ui_refresh_seconds",
    "user_paused",
    "context_carry_minutes",
    "clipboard_capture_enabled",
}

REMOVED_RUNTIME_SETTINGS = {
    "current_activity_snapshot",
    "pending_short_seconds",
    "pending_short_carry_provenance",
}


def _get_columns(conn, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _get_tables(conn) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def test_initialize_empty_database_sets_current_schema_version(tmp_path):
    from worktrace.db import CURRENT_SCHEMA_VERSION, get_connection, initialize_database

    db_path = str(tmp_path / "test.db")
    initialize_database(db_path)

    conn = get_connection()
    try:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == CURRENT_SCHEMA_VERSION
        assert "language" in _get_columns(conn, "project")
        assert "source_rule_type" in _get_columns(
            conn,
            "activity_project_assignment",
        )
    finally:
        conn.close()


def test_current_schema_initialization_is_idempotent(tmp_path):
    from worktrace.db import CURRENT_SCHEMA_VERSION, get_connection, initialize_database

    db_path = str(tmp_path / "test.db")
    initialize_database(db_path)
    initialize_database(db_path)
    conn = get_connection()
    try:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()


def test_initialize_database_migrates_v4_runtime_settings(tmp_path):
    db_path = str(tmp_path / "v4.db")
    db.configure_database(db_path)
    with db.get_connection() as conn:
        conn.executescript(db.read_schema_sql())
        conn.executescript(db.read_schema_indexes_sql())
        conn.execute("PRAGMA user_version = 4")
        db.seed_defaults(conn)
        for key, value in (
            ("current_activity_snapshot", '{"status":"normal"}'),
            ("pending_short_seconds", "9"),
            ("pending_short_carry_provenance", "legacy"),
        ):
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value, "2026-07-16 00:00:00"),
            )

    db.initialize_database(db_path)

    with db.get_connection() as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 5
        keys = {
            str(row["key"])
            for row in conn.execute("SELECT key FROM settings").fetchall()
        }
    assert not (keys & REMOVED_RUNTIME_SETTINGS)


def test_initialize_database_rejects_non_empty_old_database(tmp_path):
    db_path = str(tmp_path / "old-startup.db")
    old = sqlite3.connect(db_path)
    try:
        old.executescript(
            """
            CREATE TABLE project (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                language TEXT NOT NULL DEFAULT '中文',
                is_archived INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds INTEGER,
                app_name TEXT NOT NULL,
                process_name TEXT NOT NULL,
                window_title TEXT NOT NULL,
                file_path_hint TEXT,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                auto_classified INTEGER NOT NULL DEFAULT 0,
                manual_override INTEGER NOT NULL DEFAULT 0,
                project_id INTEGER,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE activity_project_assignment (
                activity_id INTEGER PRIMARY KEY,
                project_id INTEGER,
                confidence INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                is_manual INTEGER NOT NULL DEFAULT 0,
                suggested_project_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO project(id, name, description, language, is_archived, enabled, created_by, created_at, updated_at)
            VALUES (100, 'Legacy Client', '', '中文', 0, 1, 'user', '2026-06-01 00:00:00', '2026-06-01 00:00:00');
            INSERT INTO activity_log(id, start_time, end_time, duration_seconds, app_name, process_name, window_title, status, source, created_at, updated_at)
            VALUES (200, '2026-06-18 09:00:00', '2026-06-18 09:30:00', 1800, 'Word', 'winword.exe', 'Legacy.docx', 'normal', 'auto', '2026-06-18 09:30:00', '2026-06-18 09:30:00');
            INSERT INTO activity_project_assignment(activity_id, project_id, confidence, source, is_manual, suggested_project_name, created_at, updated_at)
            VALUES (200, 100, 80, 'keyword_rule', 0, NULL, '2026-06-18 09:30:00', '2026-06-18 09:30:00');
            """
        )
        old.commit()
    finally:
        old.close()

    with pytest.raises(ValueError, match="database_schema_incompatible"):
        db.initialize_database(db_path)


def test_initialize_database_surfaces_post_migration_index_failures(
    tmp_path,
    monkeypatch,
):
    from worktrace import db as db_module

    db_path = str(tmp_path / "bad-index.db")
    monkeypatch.setattr(
        db_module,
        "read_schema_indexes_sql",
        lambda: "CREATE INDEX broken_index ON missing_table(id);",
    )

    with pytest.raises(sqlite3.OperationalError):
        db_module.initialize_database(db_path)


def test_initialize_creates_all_current_schema_tables(temp_db):
    with db.get_connection() as conn:
        tables = _get_tables(conn)

    assert EXPECTED_TABLES.issubset(tables)


def test_initialize_seeds_default_settings(temp_db):
    with db.get_connection() as conn:
        keys = {
            row["key"]
            for row in conn.execute("SELECT key FROM settings").fetchall()
        }

    assert EXPECTED_DEFAULT_SETTINGS.issubset(keys)
    assert not (keys & REMOVED_RUNTIME_SETTINGS)


def test_initialize_seeds_default_projects(temp_db):
    with db.get_connection() as conn:
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?",
            (UNCATEGORIZED_PROJECT,),
        ).fetchone()
        excluded = conn.execute(
            "SELECT * FROM project WHERE name = ?",
            (EXCLUDED_PROJECT,),
        ).fetchone()

    assert uncategorized is not None
    assert uncategorized["created_by"] == "system"
    assert uncategorized["language"] == "中文"
    assert uncategorized["enabled"] == 1
    assert excluded is not None
    assert excluded["created_by"] == "system"
    assert excluded["language"] == "中文"
    assert excluded["enabled"] == 0
    assert excluded["description"] == "命中后匿名记录"


def test_repeated_initialize_does_not_error_or_destroy_data(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Search",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(aid)

    db.initialize_database(temp_db)

    with db.get_connection() as conn:
        activity_count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_log"
        ).fetchone()["c"]
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?",
            (UNCATEGORIZED_PROJECT,),
        ).fetchone()

    assert activity_count == 1
    assert uncategorized is not None


def test_reset_database_clears_business_data_and_rebuilds_defaults(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Search",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(aid)

    db.reset_database()

    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_project_assignment").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_clipboard_event").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM report_session_operation").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM report_session_operation_member").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_project_rule").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_rule_index_state").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_rule_file_index").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_resource").fetchone()["c"] == 0
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?",
            (UNCATEGORIZED_PROJECT,),
        ).fetchone()
        excluded = conn.execute(
            "SELECT * FROM project WHERE name = ?",
            (EXCLUDED_PROJECT,),
        ).fetchone()
        keys = {
            row["key"]
            for row in conn.execute("SELECT key FROM settings").fetchall()
        }

    assert uncategorized is not None
    assert excluded is not None
    assert EXPECTED_DEFAULT_SETTINGS.issubset(keys)
    assert not (keys & REMOVED_RUNTIME_SETTINGS)


def test_legacy_migration_entrypoint_is_not_exported():
    assert not hasattr(db, "ensure_schema_migrations")
