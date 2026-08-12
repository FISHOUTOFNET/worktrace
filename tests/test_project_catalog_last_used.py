from __future__ import annotations

from worktrace import db
from worktrace.services import project_service


def _insert_activity(project_id: int, start: str, end: str, *, deleted: bool = False) -> None:
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO activity_log(
                start_time, end_time, duration_seconds, app_name, process_name,
                window_title, file_path_hint, status, source, is_deleted, is_hidden,
                created_at, updated_at
            ) VALUES (?, ?, 60, 'Editor', 'editor.exe', 'Matter', NULL,
                      'normal', 'test', ?, 0, ?, ?)
            """,
            (start, end, int(deleted), start, end),
        )
        activity_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual,
                suggested_project_name, source_rule_type, source_rule_id,
                created_at, updated_at
            ) VALUES (?, ?, 100, 'manual', 1, NULL, NULL, NULL, ?, ?)
            """,
            (activity_id, project_id, start, end),
        )


def test_selectable_and_filter_catalogs_include_latest_valid_activity_time(temp_db):
    project_id = project_service.create_project("26IP0165", "Miragene")
    _insert_activity(project_id, "2026-08-10 09:00:00", "2026-08-10 10:00:00")
    _insert_activity(project_id, "2026-08-12 14:00:00", "2026-08-12 15:30:00")
    _insert_activity(
        project_id,
        "2026-08-13 09:00:00",
        "2026-08-13 10:00:00",
        deleted=True,
    )

    selectable = {
        int(project["id"]): project for project in project_service.list_selectable_projects()
    }
    filterable = {
        int(project["id"]): project for project in project_service.list_filter_projects()
    }

    assert selectable[project_id]["last_used_at"] == "2026-08-12 15:30:00"
    assert filterable[project_id]["last_used_at"] == "2026-08-12 15:30:00"
