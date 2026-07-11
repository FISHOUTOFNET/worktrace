"""Tests for current schema initialization and reset."""
from __future__ import annotations

import sqlite3

from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
import pytest

pytestmark = [pytest.mark.db, pytest.mark.contract]


# Tables that must exist after initialize_database on an empty database.
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

# Default settings that must be seeded on a fresh database.
EXPECTED_DEFAULT_SETTINGS = {
    "poll_interval_seconds",
    "idle_threshold_seconds",
    "current_activity_snapshot",
    "pending_short_seconds",
    "pending_short_carry_provenance",
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


def _get_columns(conn, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _get_tables(conn) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }


def _drop_project_language_column(conn) -> None:
    """Remove ``language`` from ``project`` to simulate a pre-language DB."""
    conn.execute("ALTER TABLE project RENAME TO project_old")
    conn.execute(
        """
        CREATE TABLE project(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            is_archived INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'user' CHECK (
                created_by IN ('system', 'user')
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO project(id, name, description, is_archived, enabled, created_by, created_at, updated_at)
        SELECT id, name, description, is_archived, enabled, created_by, created_at, updated_at
        FROM project_old
        """
    )
    conn.execute("DROP TABLE project_old")


def test_old_database_without_project_language_gets_migrated(tmp_path):
    from worktrace.db import initialize_database, get_connection, ensure_schema_migrations
    db_path = str(tmp_path / "test.db")
    initialize_database(db_path)
    conn = get_connection()
    try:
        _drop_project_language_column(conn)
        conn.commit()
    finally:
        conn.close()

    conn = get_connection()
    try:
        assert "language" not in _get_columns(conn, "project")
        ensure_schema_migrations(conn)
        ensure_schema_migrations(conn)
        columns = _get_columns(conn, "project")
        assert "language" in columns
        languages = {
            row["name"]: row["language"]
            for row in conn.execute("SELECT name, language FROM project").fetchall()
        }
        assert languages[UNCATEGORIZED_PROJECT] == "中文"
        assert languages[EXCLUDED_PROJECT] == "中文"
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    """Running the migration twice does not fail."""
    from worktrace.db import initialize_database, get_connection, ensure_schema_migrations
    db_path = str(tmp_path / "test.db")
    initialize_database(db_path)
    conn = get_connection()
    try:
        ensure_schema_migrations(conn)
        ensure_schema_migrations(conn)  # Should not raise
    finally:
        conn.close()


def test_old_assignment_table_gets_rule_origin_columns_and_index(tmp_path):
    from worktrace.db import initialize_database, get_connection, ensure_schema_migrations
    db_path = str(tmp_path / "test.db")
    initialize_database(db_path)
    conn = get_connection()
    try:
        conn.execute("ALTER TABLE activity_project_assignment RENAME TO assignment_old")
        conn.execute(
            """
            CREATE TABLE activity_project_assignment (
                activity_id INTEGER PRIMARY KEY, project_id INTEGER,
                confidence INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL,
                is_manual INTEGER NOT NULL DEFAULT 0, suggested_project_name TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO activity_project_assignment SELECT activity_id, project_id, confidence, source, is_manual, suggested_project_name, created_at, updated_at FROM assignment_old"
        )
        conn.execute("DROP TABLE assignment_old")
        ensure_schema_migrations(conn)
        ensure_schema_migrations(conn)
        assert {"source_rule_type", "source_rule_id"}.issubset(_get_columns(conn, "activity_project_assignment"))
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(activity_project_assignment)").fetchall()}
        assert "idx_assignment_source_rule" in indexes
    finally:
        conn.close()


def test_initialize_database_migrates_real_old_database_before_indexes(tmp_path):
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

    db.initialize_database(db_path)
    db.initialize_database(db_path)

    with db.get_connection() as conn:
        project = conn.execute("SELECT * FROM project WHERE id = 100").fetchone()
        assignment = conn.execute(
            "SELECT * FROM activity_project_assignment WHERE activity_id = 200"
        ).fetchone()
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }

    assert project is not None
    assert project["name"] == "Legacy Client"
    assert project["is_deleted"] == 0
    assert project["is_archived"] == 0
    assert assignment is not None
    assert assignment["source_rule_type"] is None
    assert assignment["source_rule_id"] is None
    assert "idx_assignment_source_rule" in indexes


def test_initialize_database_surfaces_post_migration_index_failures(tmp_path, monkeypatch):
    from worktrace import db as db_module

    db_path = str(tmp_path / "bad-index.db")
    monkeypatch.setattr(db_module, "read_schema_indexes_sql", lambda: "CREATE INDEX broken_index ON missing_table(id);")

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


def test_initialize_seeds_default_projects(temp_db):
    with db.get_connection() as conn:
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)
        ).fetchone()
        excluded = conn.execute(
            "SELECT * FROM project WHERE name = ?", (EXCLUDED_PROJECT,)
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
        "Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00"
    )
    activity_service.finalize_created_activity(aid)

    # Second init should not fail or lose existing data.
    db.initialize_database(temp_db)

    with db.get_connection() as conn:
        activity_count = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"]
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)
        ).fetchone()

    assert activity_count == 1
    assert uncategorized is not None


def test_reset_database_clears_business_data_and_rebuilds_defaults(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity(
        "Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00"
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
        # Default projects are rebuilt.
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)
        ).fetchone()
        excluded = conn.execute(
            "SELECT * FROM project WHERE name = ?", (EXCLUDED_PROJECT,)
        ).fetchone()
        # Default settings are rebuilt.
        keys = {
            row["key"]
            for row in conn.execute("SELECT key FROM settings").fetchall()
        }

    assert uncategorized is not None
    assert excluded is not None
    assert EXPECTED_DEFAULT_SETTINGS.issubset(keys)


def test_legacy_project_session_override_migrates_to_edit_command(temp_db):
    from worktrace.db import ensure_schema_migrations, now_str

    ts = now_str()
    with db.get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE project_session_override (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                activity_member_hash TEXT NOT NULL,
                anchor_activity_id INTEGER NOT NULL,
                original_start_time TEXT NOT NULL,
                original_end_time TEXT NOT NULL,
                original_raw_duration_seconds INTEGER NOT NULL,
                project_id INTEGER,
                adjusted_duration_seconds INTEGER,
                note TEXT NOT NULL DEFAULT '',
                match_state TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE project_session_override_member (
                override_id INTEGER NOT NULL,
                activity_id INTEGER NOT NULL,
                report_date TEXT NOT NULL,
                slice_start_time TEXT NOT NULL,
                slice_end_time TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO activity_log(start_time, end_time, duration_seconds, app_name, process_name, window_title, status, source, created_at, updated_at)
            VALUES ('2026-06-25 09:00:00', '2026-06-25 09:10:00', 600, 'Word', 'winword.exe', 'Spec', 'normal', 'auto', ?, ?)
            """,
            (ts, ts),
        )
        activity_id = int(conn.execute("SELECT id FROM activity_log").fetchone()["id"])
        project_id = int(conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()["id"])
        cur = conn.execute(
            """
            INSERT INTO project_session_override(
                report_date, activity_member_hash, anchor_activity_id, original_start_time,
                original_end_time, original_raw_duration_seconds, project_id,
                adjusted_duration_seconds, note, match_state, created_at, updated_at
            ) VALUES ('2026-06-25', ?, ?, '2026-06-25 09:00:00', '2026-06-25 09:10:00', 600, ?, 300, 'legacy note', 'active', ?, ?)
            """,
            ("f" * 40, activity_id, project_id, ts, ts),
        )
        conn.execute(
            """
            INSERT INTO project_session_override_member(override_id, activity_id, report_date, slice_start_time, slice_end_time)
            VALUES (?, ?, '2026-06-25', '2026-06-25 09:00:00', '2026-06-25 09:10:00')
            """,
            (int(cur.lastrowid), activity_id),
        )
        before = dict(conn.execute("SELECT * FROM activity_log WHERE id = ?", (activity_id,)).fetchone())
        ensure_schema_migrations(conn)
        ensure_schema_migrations(conn)
        after = dict(conn.execute("SELECT * FROM activity_log WHERE id = ?", (activity_id,)).fetchone())
        tables = _get_tables(conn)
        command = conn.execute(
            "SELECT operation_type, payload_json, replay_order, match_state FROM report_session_operation"
        ).fetchone()
        member_count = conn.execute("SELECT COUNT(*) AS c FROM report_session_operation_member").fetchone()["c"]

    assert before == after
    assert "project_session_override" not in tables
    assert "project_session_override_member" not in tables
    assert command["operation_type"] == "edit_session"
    assert command["replay_order"] == 1
    assert command["match_state"] == "active"
    assert "legacy note" in command["payload_json"]
    assert member_count == 1
