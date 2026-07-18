from __future__ import annotations

from ..db import dict_rows, get_connection
from .project_inference_service import assign_project_for_activity


def create_rule(keyword: str, project_id: int) -> int:
    from .rule_catalog_command_service import create_keyword_rule

    return create_keyword_rule(keyword, project_id)


def list_rules(include_system: bool = False) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                pr.id, pr.pattern AS keyword, pr.project_id, pr.enabled,
                pr.created_at, pr.updated_at, p.name AS project_name
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


def apply_rules_to_activity(activity_id: int) -> None:
    assign_project_for_activity(activity_id)


def apply_rules_to_unclassified() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            WHERE a.is_deleted = 0
              AND COALESCE(apa.is_manual, 0) = 0
            """
        ).fetchall()
    for row in rows:
        apply_rules_to_activity(int(row["id"]))
