from __future__ import annotations

from ..constants import EXCLUDED_PROJECT
from ..data_generation_repository import DataGenerationNamespace
from ..db import dict_rows, get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from .project_inference_service import assign_project_for_activity


def _catalog_uow() -> DomainUnitOfWork:
    return DomainUnitOfWork((DataGenerationNamespace.CLASSIFICATION_CATALOG,))


def _add_privacy_effect_for_project_id(
    uow: DomainUnitOfWork,
    conn,
    project_id: int,
) -> None:
    row = conn.execute(
        "SELECT name FROM project WHERE id = ?",
        (int(project_id),),
    ).fetchone()
    if row is not None and str(row["name"] or "") == EXCLUDED_PROJECT:
        uow.add_effects(DataGenerationNamespace.PRIVACY_CATALOG)


def create_rule(keyword: str, project_id: int) -> int:
    cleaned = keyword.strip()
    if not cleaned:
        raise ValueError("keyword is required")
    timestamp = now_str()
    with _catalog_uow() as uow:
        conn = uow.connection
        _add_privacy_effect_for_project_id(uow, conn, project_id)
        cursor = conn.execute(
            """
            INSERT INTO project_rule(
                project_id, rule_type, pattern, enabled, created_by,
                created_at, updated_at
            ) VALUES (?, 'keyword', ?, 1, 'user', ?, ?)
            """,
            (project_id, cleaned, timestamp, timestamp),
        )
        return int(cursor.lastrowid)


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
    requested = int(enabled)
    with _catalog_uow() as uow:
        conn = uow.connection
        row = conn.execute(
            "SELECT project_id, enabled FROM project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
        if row is None or int(row["enabled"] or 0) == requested:
            return
        _add_privacy_effect_for_project_id(uow, conn, int(row["project_id"]))
        conn.execute(
            "UPDATE project_rule SET enabled = ?, updated_at = ? WHERE id = ?",
            (requested, now_str(), rule_id),
        )


def update_rule(rule_id: int, keyword: str) -> None:
    cleaned = keyword.strip()
    if not cleaned:
        raise ValueError("keyword is required")
    with _catalog_uow() as uow:
        conn = uow.connection
        row = conn.execute(
            """
            SELECT project_id, pattern
            FROM project_rule
            WHERE id = ? AND rule_type = 'keyword'
            """,
            (rule_id,),
        ).fetchone()
        if row is None or str(row["pattern"] or "") == cleaned:
            return
        _add_privacy_effect_for_project_id(uow, conn, int(row["project_id"]))
        conn.execute(
            """
            UPDATE project_rule
            SET pattern = ?, updated_at = ?
            WHERE id = ? AND rule_type = 'keyword'
            """,
            (cleaned, now_str(), rule_id),
        )


def delete_rule(rule_id: int) -> bool:
    with _catalog_uow() as uow:
        conn = uow.connection
        row = conn.execute(
            """
            SELECT project_id
            FROM project_rule
            WHERE id = ? AND rule_type = 'keyword'
            """,
            (rule_id,),
        ).fetchone()
        if row is None:
            return False
        _add_privacy_effect_for_project_id(uow, conn, int(row["project_id"]))
        cursor = conn.execute(
            "DELETE FROM project_rule WHERE id = ? AND rule_type = 'keyword'",
            (rule_id,),
        )
        return cursor.rowcount == 1


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
