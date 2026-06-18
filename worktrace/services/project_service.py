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
            INSERT INTO project(name, description, default_billable, is_archived, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
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
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM project WHERE is_archived = 0 ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return dict_rows(rows)


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
            INSERT INTO project(name, description, default_billable, is_archived, created_at, updated_at)
            VALUES (?, '', 1, 0, ?, ?)
            """,
            (UNCATEGORIZED_PROJECT, ts, ts),
        )
        return int(cur.lastrowid)
