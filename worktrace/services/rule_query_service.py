"""Read-only direct rule lookups used by transport facades."""
from __future__ import annotations

from ..db import get_connection


def get_keyword_rule(rule_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT pr.id, pr.pattern AS keyword, pr.normalized_pattern,
                   pr.project_id, pr.enabled, pr.created_at, pr.updated_at,
                   p.name AS project_name
            FROM project_rule pr
            LEFT JOIN project p ON p.id = pr.project_id
            WHERE pr.id = ? AND pr.rule_type = 'keyword'
            """,
            (int(rule_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def get_folder_rule(rule_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT fpr.*, p.name AS project_name
            FROM folder_project_rule fpr
            LEFT JOIN project p ON p.id = fpr.project_id
            WHERE fpr.id = ?
            """,
            (int(rule_id),),
        ).fetchone()
    return dict(row) if row is not None else None


__all__ = ["get_folder_rule", "get_keyword_rule"]
