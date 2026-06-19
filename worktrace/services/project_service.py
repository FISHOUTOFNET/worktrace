from __future__ import annotations

from ..constants import UNCATEGORIZED_PROJECT
from ..db import dict_rows, get_connection, now_str


def create_project(name: str, description: str = "", default_billable: bool = True) -> int:
    name = name.strip()
    if not name:
        raise ValueError("project name is required")
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO project(name, description, default_billable, is_archived, created_by, created_at, updated_at)
            VALUES (?, ?, ?, 0, 'user', ?, ?)
            """,
            (name, description, int(default_billable), ts, ts),
        )
        return int(cur.lastrowid)


def get_project(project_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def get_project_by_name(name: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM project WHERE name = ?", (name.strip(),)).fetchone()
    return dict(row) if row else None


def get_or_create_project(name: str) -> int:
    existing = get_project_by_name(name)
    if existing:
        return int(existing["id"])
    return create_project(name)


def list_active_projects() -> list[dict]:
    return list_selectable_projects()


def list_user_projects() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project
            WHERE is_archived = 0 AND created_by = 'user'
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
    return dict_rows(rows)


def list_selectable_projects() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project
            WHERE is_archived = 0
              AND (created_by = 'user' OR name = ?)
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, name COLLATE NOCASE
            """,
            (UNCATEGORIZED_PROJECT, UNCATEGORIZED_PROJECT),
        ).fetchall()
    return dict_rows(rows)


def list_project_bindings() -> list[dict]:
    projects = list_user_projects()
    with get_connection() as conn:
        folder_rows = dict_rows(
            conn.execute(
                """
                SELECT fpr.*, p.name AS project_name
                FROM folder_project_rule fpr
                LEFT JOIN project p ON p.id = fpr.project_id
                ORDER BY fpr.folder_path COLLATE NOCASE, fpr.id
                """
            ).fetchall()
        )
        resource_rows = dict_rows(
            conn.execute(
                """
                SELECT r.id, r.display_name, r.full_path, r.parent_dir, r.default_project_id,
                       p.name AS project_name
                FROM resource r
                LEFT JOIN project p ON p.id = r.default_project_id
                WHERE r.default_project_id IS NOT NULL
                  AND r.resource_role = 'anchor'
                  AND r.resource_type = 'file'
                ORDER BY r.display_name COLLATE NOCASE, r.id
                """
            ).fetchall()
        )
    by_project = {
        int(project["id"]): {**project, "folder_rules": [], "file_defaults": []}
        for project in projects
    }
    for row in folder_rows:
        project = by_project.get(int(row["project_id"]))
        if project is not None:
            project["folder_rules"].append(row)
    for row in resource_rows:
        project = by_project.get(int(row["default_project_id"]))
        if project is not None:
            project["file_defaults"].append(row)
    return list(by_project.values())


def archive_project(project_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE project SET is_archived = 1, updated_at = ? WHERE id = ?",
            (now_str(), project_id),
        )


def get_or_create_uncategorized_project() -> int:
    ts = now_str()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()
        if row:
            return int(row["id"])
        cur = conn.execute(
            """
            INSERT INTO project(name, description, default_billable, is_archived, created_by, created_at, updated_at)
            VALUES (?, '', 1, 0, 'system', ?, ?)
            """,
            (UNCATEGORIZED_PROJECT, ts, ts),
        )
        return int(cur.lastrowid)
