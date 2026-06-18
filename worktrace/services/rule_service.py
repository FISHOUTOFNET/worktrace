from __future__ import annotations

from ..db import dict_rows, get_connection, now_str
from .project_inference_service import assign_project_for_activity


def create_rule(keyword: str, project_id: int) -> int:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword is required")
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO rule(keyword, project_id, enabled, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (keyword, project_id, ts, ts),
        )
        conn.execute(
            """
            INSERT INTO project_rule(project_id, rule_type, pattern, enabled, created_by, created_at, updated_at)
            VALUES (?, 'keyword', ?, 1, 'user', ?, ?)
            """,
            (project_id, keyword, ts, ts),
        )
        return int(cur.lastrowid)


def list_rules() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                pr.id,
                pr.pattern AS keyword,
                pr.project_id,
                pr.enabled,
                pr.created_at,
                pr.updated_at,
                p.name AS project_name
            FROM project_rule pr
            LEFT JOIN project p ON p.id = pr.project_id
            WHERE pr.rule_type = 'keyword'
            ORDER BY pr.created_at, pr.id
            """
        ).fetchall()
    return dict_rows(rows)


def apply_rules_to_activity(activity_id: int) -> None:
    assign_project_for_activity(activity_id)


def apply_rules_to_unclassified() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM activity_log WHERE manual_override = 0 AND is_deleted = 0"
        ).fetchall()
    for row in rows:
        apply_rules_to_activity(int(row["id"]))
