from __future__ import annotations

from ..db import dict_rows, get_connection, now_str
from ..mutation_effects import report_structure_mutation
from .project_inference_service import assign_project_for_activity, invalidate_keyword_rule_cache


@report_structure_mutation
def create_rule(keyword: str, project_id: int) -> int:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword is required")
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO project_rule(project_id, rule_type, pattern, enabled, created_by, created_at, updated_at)
            VALUES (?, 'keyword', ?, 1, 'user', ?, ?)
            """,
            (project_id, keyword, ts, ts),
        )
        rule_id = int(cur.lastrowid)
    invalidate_keyword_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()
    return rule_id


def list_rules(include_system: bool = False) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT pr.id, pr.pattern AS keyword, pr.project_id, pr.enabled,
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


@report_structure_mutation
def set_rule_enabled(rule_id: int, enabled: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE project_rule SET enabled = ?, updated_at = ? WHERE id = ?",
            (int(enabled), now_str(), rule_id),
        )
    invalidate_keyword_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()


@report_structure_mutation
def update_rule(rule_id: int, keyword: str) -> None:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword is required")
    with get_connection() as conn:
        conn.execute(
            "UPDATE project_rule SET pattern = ?, updated_at = ? "
            "WHERE id = ? AND rule_type = 'keyword'",
            (keyword, now_str(), rule_id),
        )
    invalidate_keyword_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()


@report_structure_mutation
def delete_rule(rule_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM project_rule WHERE id = ?", (rule_id,))
    invalidate_keyword_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()


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
