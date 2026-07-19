from __future__ import annotations

from ..db import dict_rows, get_connection


def create_rule(keyword: str, project_id: int) -> int:
    from .rule_catalog_command_service import create_keyword_rule

    return create_keyword_rule(keyword, project_id)


def get_rule(rule_id: int) -> dict | None:
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


def list_rules(include_system: bool = False) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                pr.id, pr.pattern AS keyword, pr.normalized_pattern,
                pr.project_id, pr.enabled, pr.created_at, pr.updated_at,
                p.name AS project_name
            FROM project_rule pr
            LEFT JOIN project p ON p.id = pr.project_id
            WHERE pr.rule_type = 'keyword'
              AND (? = 1 OR pr.created_by = 'user')
            ORDER BY pr.created_at, pr.id
            """,
            (int(include_system),),
        ).fetchall()
    return dict_rows(rows)


def set_rule_enabled(rule_id: int, enabled: bool) -> None:
    from .rule_catalog_command_service import set_keyword_rule_enabled

    set_keyword_rule_enabled(rule_id, enabled)


def update_rule(rule_id: int, keyword: str) -> None:
    from .rule_catalog_command_service import update_keyword_rule

    update_keyword_rule(rule_id, keyword)


def delete_rule(rule_id: int) -> bool:
    from .rule_catalog_command_service import delete_keyword_rule

    return delete_keyword_rule(rule_id)
