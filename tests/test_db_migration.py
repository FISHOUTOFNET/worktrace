"""Tests for idempotent database schema migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT


def _create_old_database(path: Path) -> None:
    """Create a database with an older schema that is missing columns and tables."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        CREATE TABLE project (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            is_archived INTEGER NOT NULL DEFAULT 0,
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
            status TEXT NOT NULL CHECK (
                status IN ('normal', 'idle', 'paused', 'error')
            ),
            source TEXT NOT NULL CHECK (
                source IN ('auto', 'manual', 'system')
            ),
            is_deleted INTEGER NOT NULL DEFAULT 0,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            project_id INTEGER,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES project(id)
        );

        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE session_boundary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE folder_project_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path TEXT NOT NULL,
            normalized_folder_key TEXT NOT NULL UNIQUE,
            project_id INTEGER NOT NULL,
            recursive INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES project(id)
        );

        CREATE TABLE project_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            rule_type TEXT NOT NULL,
            pattern TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES project(id)
        );

        CREATE TABLE activity_project_assignment (
            activity_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            confidence INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL CHECK (
                source IN ('manual', 'anchor_context', 'uncategorized')
            ),
            is_manual INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (activity_id) REFERENCES activity_log(id),
            FOREIGN KEY (project_id) REFERENCES project(id)
        );

        CREATE TABLE manual_project_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE manual_project_session_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            activity_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES manual_project_session(id),
            FOREIGN KEY (activity_id) REFERENCES activity_log(id)
        );
        """
    )
    # Insert some data
    conn.execute(
        "INSERT INTO project(name, description, is_archived, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
        ("TestProject", "A test project", "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
    )
    conn.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES ('poll_interval_seconds', '3', '2026-01-01 00:00:00')",
    )
    conn.execute(
        "INSERT INTO activity_log(start_time, end_time, duration_seconds, app_name, process_name, window_title, status, source, is_deleted, is_hidden, project_id, note, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, '', ?, ?)",
        ("2026-01-01 09:00:00", "2026-01-01 09:30:00", 1800, "Notepad", "notepad.exe", "test.txt - Notepad", "normal", "auto", 1, "2026-01-01 09:00:00", "2026-01-01 09:30:00"),
    )
    conn.commit()
    conn.close()


def test_migrate_old_database_adds_missing_columns(tmp_path):
    path = tmp_path / "worktrace.db"
    _create_old_database(path)
    db.initialize_database(path)

    with db.get_connection() as conn:
        activity_cols = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        project_cols = {row["name"] for row in conn.execute("PRAGMA table_info(project)").fetchall()}
        assignment_cols = {row["name"] for row in conn.execute("PRAGMA table_info(activity_project_assignment)").fetchall()}

    assert "file_path_hint" in activity_cols
    assert "auto_classified" in activity_cols
    assert "manual_override" in activity_cols
    assert "created_by" in project_cols
    assert "enabled" in project_cols
    assert "suggested_project_name" in assignment_cols


def test_migrate_old_database_preserves_activity_data(tmp_path):
    path = tmp_path / "worktrace.db"
    _create_old_database(path)
    db.initialize_database(path)

    with db.get_connection() as conn:
        row = conn.execute("SELECT app_name, process_name, window_title, status FROM activity_log WHERE id = 1").fetchone()

    assert row is not None
    assert row["app_name"] == "Notepad"
    assert row["process_name"] == "notepad.exe"
    assert row["window_title"] == "test.txt - Notepad"
    assert row["status"] == "normal"


def test_migrate_old_database_preserves_project_data(tmp_path):
    path = tmp_path / "worktrace.db"
    _create_old_database(path)
    db.initialize_database(path)

    with db.get_connection() as conn:
        row = conn.execute("SELECT name, description FROM project WHERE name = 'TestProject'").fetchone()

    assert row is not None
    assert row["name"] == "TestProject"
    assert row["description"] == "A test project"


def test_migrate_drops_deprecated_tables(tmp_path):
    path = tmp_path / "worktrace.db"
    _create_old_database(path)
    db.initialize_database(path)

    with db.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }

    assert "manual_project_session" not in tables
    assert "manual_project_session_activity" not in tables


def test_migrate_idempotent_repeated_calls(tmp_path):
    path = tmp_path / "worktrace.db"
    _create_old_database(path)
    db.initialize_database(path)

    # Insert extra data after first init
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO project(name, description, is_archived, enabled, created_by, created_at, updated_at) "
            "VALUES (?, '', 0, 1, 'user', ?, ?)",
            ("SecondProject", "2026-06-01 00:00:00", "2026-06-01 00:00:00"),
        )

    # Second init should not fail or lose data
    db.initialize_database(path)

    with db.get_connection() as conn:
        projects = {row["name"] for row in conn.execute("SELECT name FROM project").fetchall()}
        activity_count = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"]

    assert "TestProject" in projects
    assert "SecondProject" in projects
    assert activity_count == 1


def test_schema_version_written_on_init(tmp_path):
    path = tmp_path / "worktrace.db"
    db.initialize_database(path)

    with db.get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()

    assert row is not None
    assert int(row["value"]) == db.CURRENT_SCHEMA_VERSION


def test_migrate_old_database_creates_missing_tables(tmp_path):
    path = tmp_path / "worktrace.db"
    _create_old_database(path)
    db.initialize_database(path)

    with db.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }

    assert "activity_clipboard_event" in tables
    assert "project_session_note" in tables
    assert "folder_rule_index_state" in tables
    assert "folder_rule_file_index" in tables


def test_migrate_rebuilds_activity_log_with_correct_check_constraints(tmp_path):
    path = tmp_path / "worktrace.db"
    _create_old_database(path)
    db.initialize_database(path)

    with db.get_connection() as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'activity_log'"
        ).fetchone()["sql"]

    assert "excluded" in sql
    assert "auto" in sql
