from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT


def test_new_database_has_current_schema_and_defaults(temp_db):
    with db.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        resource_columns = {row["name"] for row in conn.execute("PRAGMA table_info(resource)").fetchall()}
        project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(project)").fetchall()}
        assignment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(activity_project_assignment)").fetchall()
        }
        setting = conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()
        idle_threshold = conn.execute("SELECT value FROM settings WHERE key = 'idle_threshold_seconds'").fetchone()
        ui_refresh = conn.execute("SELECT value FROM settings WHERE key = 'ui_refresh_seconds'").fetchone()
        removed_setting = conn.execute("SELECT value FROM settings WHERE key = 'default_billable'").fetchone()
        min_history = conn.execute("SELECT value FROM settings WHERE key = 'min_history_seconds'").fetchone()
        min_idle = conn.execute("SELECT value FROM settings WHERE key = 'min_idle_segment_seconds'").fetchone()
        uncategorized = conn.execute("SELECT * FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()
        excluded = conn.execute("SELECT * FROM project WHERE name = ?", (EXCLUDED_PROJECT,)).fetchone()
        exclude_rule_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM project_rule pr
            JOIN project p ON p.id = pr.project_id
            WHERE p.name = ?
            """,
            (EXCLUDED_PROJECT,),
        ).fetchone()
        resource_schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'resource'"
        ).fetchone()["sql"]

    assert "resource_id" in activity_columns
    assert "file_path_hint" in activity_columns
    assert "is_billable" not in activity_columns
    assert "is_confirmed" not in activity_columns
    assert "created_by" in project_columns
    assert "enabled" in project_columns
    assert "default_billable" not in project_columns
    assert "suggested_project_name" in assignment_columns
    assert {"full_path", "parent_dir", "file_stem"} <= resource_columns
    assert "resource" in tables
    assert "project_rule" in tables
    assert "folder_project_rule" in tables
    assert "activity_project_assignment" in tables
    assert setting["value"] == "15"
    assert idle_threshold["value"] == "300"
    assert ui_refresh["value"] == "10"
    assert removed_setting is None
    assert min_history is None
    assert min_idle is None
    assert uncategorized is not None
    assert uncategorized["created_by"] == "system"
    assert excluded is not None
    assert excluded["created_by"] == "system"
    assert excluded["enabled"] == 1
    assert exclude_rule_count["c"] == 4
    assert "'file', 'app'" in resource_schema
    assert "web" not in resource_schema
    assert "communication" not in resource_schema
    assert "meeting" not in resource_schema
    assert "unknown" not in resource_schema
    assert "rule" not in tables


def test_reset_database_clears_current_schema_tables(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity("Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00")
    activity_service.finalize_created_activity(aid)

    db.reset_database()

    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM resource").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_project_rule").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"] == 4
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        resource_columns = {row["name"] for row in conn.execute("PRAGMA table_info(resource)").fetchall()}
        project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(project)").fetchall()}
        assignment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(activity_project_assignment)").fetchall()
        }
        assert "file_path_hint" in activity_columns
        assert "is_billable" not in activity_columns
        assert "is_confirmed" not in activity_columns
        assert "created_by" in project_columns
        assert "enabled" in project_columns
        assert "default_billable" not in project_columns
        assert "suggested_project_name" in assignment_columns
        assert {"full_path", "parent_dir", "file_stem"} <= resource_columns
        assert conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()["value"] == "15"
        assert conn.execute("SELECT value FROM settings WHERE key = 'idle_threshold_seconds'").fetchone()["value"] == "300"
        assert conn.execute("SELECT value FROM settings WHERE key = 'ui_refresh_seconds'").fetchone()["value"] == "10"
        assert conn.execute("SELECT value FROM settings WHERE key = 'default_billable'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key = 'min_history_seconds'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key = 'min_idle_segment_seconds'").fetchone() is None
        assert conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone() is not None
        assert conn.execute("SELECT id FROM project WHERE name = ?", (EXCLUDED_PROJECT,)).fetchone() is not None
