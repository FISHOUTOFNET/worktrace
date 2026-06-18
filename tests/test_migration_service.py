import sqlite3

from worktrace import db


OLD_SCHEMA = """
CREATE TABLE project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    default_billable INTEGER NOT NULL DEFAULT 1,
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
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    is_billable INTEGER NOT NULL DEFAULT 1,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    is_confirmed INTEGER NOT NULL DEFAULT 0,
    auto_classified INTEGER NOT NULL DEFAULT 0,
    manual_override INTEGER NOT NULL DEFAULT 0,
    project_id INTEGER,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def test_new_database_has_new_schema_and_defaults(temp_db):
    with db.get_connection() as conn:
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        setting = conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()
    assert "resource_id" in activity_columns
    assert {"resource", "project_rule", "activity_project_assignment"}.issubset(tables)
    assert setting["value"] == "15"


def test_old_database_migrates_idempotently(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO project(name, description, created_at, updated_at) VALUES ('未归类', '', '2026-06-18 09:00:00', '2026-06-18 09:00:00')"
    )
    conn.execute(
        "INSERT INTO project(name, description, created_at, updated_at) VALUES ('A', '', '2026-06-18 09:00:00', '2026-06-18 09:00:00')"
    )
    conn.execute(
        "INSERT INTO rule(keyword, project_id, enabled, created_at, updated_at) VALUES ('A_file', 2, 1, '2026-06-18 09:00:00', '2026-06-18 09:00:00')"
    )
    conn.execute(
        """
        INSERT INTO activity_log(
            start_time, end_time, duration_seconds, app_name, process_name, window_title,
            status, source, project_id, created_at, updated_at
        )
        VALUES ('2026-06-18 09:00:00', '2026-06-18 09:10:00', 600, 'Edge', 'msedge.exe', 'Search', 'normal', 'auto', 1, '2026-06-18 09:00:00', '2026-06-18 09:00:00')
        """
    )
    conn.commit()
    conn.close()

    db.initialize_database(path)
    db.initialize_database(path)

    with db.get_connection() as conn:
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        rule_count = conn.execute("SELECT COUNT(*) AS c FROM project_rule WHERE pattern = 'A_file'").fetchone()["c"]
        browser_count = conn.execute("SELECT COUNT(*) AS c FROM resource WHERE canonical_key = 'web:browser'").fetchone()["c"]
        assignment_count = conn.execute("SELECT COUNT(*) AS c FROM activity_project_assignment").fetchone()["c"]
        resource_id = conn.execute("SELECT resource_id FROM activity_log WHERE id = 1").fetchone()["resource_id"]
    assert "resource_id" in activity_columns
    assert rule_count == 1
    assert browser_count == 1
    assert assignment_count == 1
    assert resource_id is not None


def test_reset_database_clears_new_tables(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity("Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00")
    activity_service.finalize_created_activity(aid)
    db.reset_database()
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM resource").fetchone()["c"] == 0
        assert conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()["value"] == "15"
        assert conn.execute("SELECT id FROM project WHERE name = '未归类'").fetchone() is not None
