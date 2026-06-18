from worktrace import db
from worktrace.constants import UNCATEGORIZED_PROJECT


def test_new_database_has_current_schema_and_defaults(temp_db):
    with db.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        setting = conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()
        uncategorized = conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()

    assert "resource_id" in activity_columns
    assert "resource" in tables
    assert "project_rule" in tables
    assert "activity_project_assignment" in tables
    assert setting["value"] == "15"
    assert uncategorized is not None
    assert "rule" not in tables


def test_reset_database_clears_current_schema_tables(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity("Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00")
    activity_service.finalize_created_activity(aid)

    db.reset_database()

    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM resource").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"] == 0
        assert conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()["value"] == "15"
        assert conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone() is not None
