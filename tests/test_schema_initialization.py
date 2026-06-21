from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT


def test_new_database_has_current_schema_and_defaults(temp_db):
    with db.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
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
        min_activity = conn.execute("SELECT value FROM settings WHERE key = 'min_activity_seconds'").fetchone()
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
        assignment_schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'activity_project_assignment'"
        ).fetchone()["sql"]

    assert "resource_id" not in activity_columns
    assert "file_path_hint" in activity_columns
    assert "is_billable" not in activity_columns
    assert "is_confirmed" not in activity_columns
    assert "created_by" in project_columns
    assert "enabled" in project_columns
    assert "default_billable" not in project_columns
    assert "suggested_project_name" in assignment_columns
    assert "resource" not in tables
    assert "project_rule" in tables
    assert "folder_project_rule" in tables
    assert "activity_project_assignment" in tables
    assert "manual_project_session" not in tables
    assert "manual_project_session_activity" not in tables
    assert setting["value"] == "15"
    assert idle_threshold["value"] == "300"
    assert ui_refresh["value"] == "10"
    assert removed_setting is None
    assert min_history is None
    assert min_idle is None
    assert min_activity is None
    assert uncategorized is not None
    assert uncategorized["created_by"] == "system"
    assert excluded is not None
    assert excluded["created_by"] == "system"
    assert excluded["enabled"] == 0
    assert excluded["description"] == "命中后匿名记录"
    assert exclude_rule_count["c"] == 0
    assert "midnight_anchor" in assignment_schema
    assert "keyword_rule" in assignment_schema
    assert "anchor_keyword" not in assignment_schema
    assert "anchor_resource_default" not in assignment_schema
    assert "rule" not in tables


def test_reset_database_clears_current_schema_tables(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity("Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00")
    activity_service.finalize_created_activity(aid)

    db.reset_database()

    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_project_rule").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"] == 0
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
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
        assert conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()["value"] == "15"
        assert conn.execute("SELECT value FROM settings WHERE key = 'idle_threshold_seconds'").fetchone()["value"] == "300"
        assert conn.execute("SELECT value FROM settings WHERE key = 'ui_refresh_seconds'").fetchone()["value"] == "10"
        assert conn.execute("SELECT value FROM settings WHERE key = 'default_billable'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key = 'min_history_seconds'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key = 'min_idle_segment_seconds'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key = 'min_activity_seconds'").fetchone() is None
        assert conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone() is not None
        assert conn.execute("SELECT id FROM project WHERE name = ?", (EXCLUDED_PROJECT,)).fetchone() is not None


def test_seed_defaults_removes_only_old_system_exclude_keywords(temp_db):
    from worktrace.services import project_service, rule_service

    excluded_id = project_service.get_or_create_excluded_project()
    user_rule_id = rule_service.create_rule("银行", excluded_id)
    with db.get_connection() as conn:
        for keyword in ["微信", "银行", "密码", "个人"]:
            conn.execute(
                """
                INSERT INTO project_rule(project_id, rule_type, pattern, enabled, created_by, created_at, updated_at)
                VALUES (?, 'keyword', ?, 1, 'system', '2026-06-18 09:00:00', '2026-06-18 09:00:00')
                """,
                (excluded_id, keyword),
            )

    with db.get_connection() as conn:
        db.seed_defaults(conn)

    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, pattern, created_by
            FROM project_rule
            WHERE project_id = ?
            ORDER BY id
            """,
            (excluded_id,),
        ).fetchall()

    assert [(row["id"], row["pattern"], row["created_by"]) for row in rows] == [(user_rule_id, "银行", "user")]
