"""Tests for current schema initialization and reset."""
from __future__ import annotations

from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT


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
    "project_session_note",
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


def _drop_adjusted_duration_column(conn) -> None:
    """Remove ``adjusted_duration_seconds`` from ``project_session_note``.

    Uses the rename-and-recreate pattern so the migration test works on
    SQLite versions that do not support ``ALTER TABLE ... DROP COLUMN``
    (pre 3.35.0). The schema for ``project_session_note`` matches the
    pre-migration shape (no ``adjusted_duration_seconds`` column).
    """
    conn.execute("ALTER TABLE project_session_note RENAME TO project_session_note_old")
    conn.execute(
        """
        CREATE TABLE project_session_note(
            report_date TEXT NOT NULL,
            first_activity_id INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (report_date, first_activity_id)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO project_session_note(report_date, first_activity_id, note, created_at, updated_at)
        SELECT report_date, first_activity_id, note, created_at, updated_at
        FROM project_session_note_old
        """
    )
    conn.execute("DROP TABLE project_session_note_old")


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


def test_old_database_without_adjusted_duration_gets_migrated(tmp_path):
    """An old database missing adjusted_duration_seconds gets the column added."""
    from worktrace.db import initialize_database, get_connection, ensure_schema_migrations
    db_path = str(tmp_path / "test.db")
    # Create a new-style database, then strip the column to simulate an
    # old database that predates the migration.
    initialize_database(db_path)
    conn = get_connection()
    try:
        _drop_adjusted_duration_column(conn)
        conn.commit()
    finally:
        conn.close()
    # Verify column is gone
    conn = get_connection()
    try:
        columns = _get_columns(conn, "project_session_note")
        assert "adjusted_duration_seconds" not in columns
    finally:
        conn.close()
    # Run migration
    conn = get_connection()
    try:
        ensure_schema_migrations(conn)
    finally:
        conn.close()
    # Verify column is back
    conn = get_connection()
    try:
        columns = _get_columns(conn, "project_session_note")
        assert "adjusted_duration_seconds" in columns
    finally:
        conn.close()


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
        assert conn.execute("SELECT COUNT(*) AS c FROM project_session_note").fetchone()["c"] == 0
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
