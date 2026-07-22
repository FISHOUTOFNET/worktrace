from __future__ import annotations

import sqlite3

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from ..data_generation_repository import DataGenerationNamespace
from ..db import dict_rows, get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import project_lifecycle_policy
from .project_command_policy import ProjectLifecycleError
from .system_project_service import require_excluded_project_id


def _catalog_uow(
    *extra_effects: DataGenerationNamespace,
) -> DomainUnitOfWork:
    return DomainUnitOfWork(
        (
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
            *extra_effects,
        )
    )


def _add_privacy_effect_for_project(
    uow: DomainUnitOfWork,
    project: dict | None,
) -> None:
    if project and str(project.get("name") or "") == EXCLUDED_PROJECT:
        uow.add_effects(DataGenerationNamespace.PRIVACY_CATALOG)


def _normalize_project_language(language: str | None = None) -> str:
    cleaned = (language or "").strip()
    return cleaned or "中文"


def require_mutable_user_project(conn, project_id: int) -> dict:
    """Load and validate one mutable, active user project in this transaction."""

    row = conn.execute(
        "SELECT * FROM project WHERE id = ?",
        (int(project_id),),
    ).fetchone()
    project = dict(row) if row is not None else None
    if project is None:
        raise ProjectLifecycleError("not_found")
    if project_lifecycle_policy.project_is_system_or_special(project):
        raise ProjectLifecycleError("system_project")
    if (
        project_lifecycle_policy.project_is_deleted(project)
        or project_lifecycle_policy.project_is_archived(project)
    ):
        raise ProjectLifecycleError("project_not_available")
    return project


def _raise_project_integrity(exc: sqlite3.IntegrityError) -> None:
    message = str(exc).casefold()
    if "project.name" in message or "reserved_project_name" in message:
        code = (
            "system_project"
            if "reserved_project_name" in message
            else "duplicate_project"
        )
        raise ProjectLifecycleError(code) from exc
    raise exc


def create_project(
    name: str,
    description: str = "",
    language: str = "中文",
) -> int:
    cleaned = name.strip()
    if not cleaned:
        raise ProjectLifecycleError("invalid_input")
    if project_lifecycle_policy.project_name_is_reserved(cleaned):
        raise ProjectLifecycleError("system_project")
    timestamp = now_str()
    with _catalog_uow() as uow:
        try:
            cursor = uow.connection.execute(
                """
                INSERT INTO project(
                    name, description, language, is_archived, enabled,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, 0, 1, 'user', ?, ?)
                """,
                (
                    cleaned,
                    description,
                    _normalize_project_language(language),
                    timestamp,
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            _raise_project_integrity(exc)
        uow.mark_changed(
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )
        return int(cursor.lastrowid)


def update_project(
    project_id: int,
    name: str,
    description: str = "",
    language: str = "中文",
) -> None:
    cleaned = name.strip()
    if not cleaned:
        raise ProjectLifecycleError("invalid_input")
    if project_lifecycle_policy.project_name_is_reserved(cleaned):
        raise ProjectLifecycleError("system_project")
    normalized_description = description.strip()
    normalized_language = _normalize_project_language(language)
    with _catalog_uow() as uow:
        conn = uow.connection
        project = require_mutable_user_project(conn, project_id)
        if (
            str(project.get("name") or "") == cleaned
            and str(project.get("description") or "") == normalized_description
            and str(project.get("language") or "") == normalized_language
        ):
            return
        try:
            conn.execute(
                """
                UPDATE project
                SET name = ?, description = ?, language = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cleaned,
                    normalized_description,
                    normalized_language,
                    now_str(),
                    project_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            _raise_project_integrity(exc)
        uow.mark_changed(
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )


def set_project_enabled(project_id: int, enabled: bool) -> None:
    requested = int(enabled)
    with _catalog_uow() as uow:
        conn = uow.connection
        project = require_mutable_user_project(conn, project_id)
        if int(project.get("enabled") or 0) == requested:
            return
        conn.execute(
            "UPDATE project SET enabled = ?, updated_at = ? WHERE id = ?",
            (requested, now_str(), project_id),
        )
        uow.mark_changed(
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )


def set_excluded_project_enabled(enabled: bool) -> int:
    project_id = require_excluded_project_id()
    requested = int(enabled)
    with _catalog_uow(DataGenerationNamespace.PRIVACY_CATALOG) as uow:
        conn = uow.connection
        row = conn.execute(
            "SELECT enabled FROM project WHERE id = ? AND name = ?",
            (project_id, EXCLUDED_PROJECT),
        ).fetchone()
        if row is not None and int(row["enabled"] or 0) == requested:
            return project_id
        conn.execute(
            """
            UPDATE project
            SET enabled = ?, updated_at = ?
            WHERE id = ? AND name = ?
            """,
            (requested, now_str(), project_id, EXCLUDED_PROJECT),
        )
        uow.mark_changed(
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
            DataGenerationNamespace.PRIVACY_CATALOG,
        )
    return project_id


def get_project(project_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project WHERE id = ?",
            (project_id,),
        ).fetchone()
    return dict(row) if row else None


def get_project_by_name(name: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project WHERE name = ?",
            (name.strip(),),
        ).fetchone()
    return dict(row) if row else None


def is_concrete_project_id(project_id: int | None) -> bool:
    if not project_id:
        return False
    project = get_project(int(project_id))
    if not project:
        return False
    return project.get("name") not in {UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT}


def list_active_projects() -> list[dict]:
    return list_selectable_projects()


def list_user_projects() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM project ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [
        row
        for row in dict_rows(rows)
        if not project_lifecycle_policy.project_is_deleted(row)
        and not project_lifecycle_policy.project_is_archived(row)
        and row.get("created_by") == "user"
    ]


def list_selectable_projects() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END,
                     name COLLATE NOCASE
            """,
            (UNCATEGORIZED_PROJECT,),
        ).fetchall()
    return [
        row
        for row in dict_rows(rows)
        if project_lifecycle_policy.project_selectable_for_editing(row)
    ]


def list_rule_target_projects() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM project ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [
        row
        for row in dict_rows(rows)
        if project_lifecycle_policy.project_available_for_rules(row)
    ]


def _project_duration_totals(conn) -> dict[int, int]:
    """Build the authoritative all-time project totals once for Project Rules."""

    from .report_projection_snapshot_service import build_visible_snapshot

    snapshot = build_visible_snapshot("1970-01-01", now_str()[:10], conn=conn)
    totals: dict[int, int] = {}
    for entry in snapshot.final_entries:
        if bool(entry.get("is_in_progress")):
            continue
        project_id = int(entry.get("report_project_id") or entry.get("project_id") or 0)
        if project_id > 0:
            totals[project_id] = totals.get(project_id, 0) + int(
                entry.get("duration_seconds") or 0
            )
    return totals


def _list_project_bindings(
    include_system_special: bool,
    *,
    include_total_duration: bool,
) -> list[dict]:
    with get_connection() as conn:
        conn.execute("BEGIN")
        rows = conn.execute(
            """
            SELECT *
            FROM project
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END,
                     name COLLATE NOCASE
            """,
            (EXCLUDED_PROJECT,),
        ).fetchall()
        last_used_rows = dict_rows(
            conn.execute(
                """
                SELECT apa.project_id AS project_id,
                       MAX(COALESCE(al.end_time, al.start_time)) AS last_used_at
                FROM activity_log al
                LEFT JOIN activity_project_assignment apa
                  ON apa.activity_id = al.id
                WHERE al.is_deleted = 0
                  AND apa.project_id IS NOT NULL
                GROUP BY apa.project_id
                """
            ).fetchall()
        )
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
        keyword_rows = dict_rows(
            conn.execute(
                """
                SELECT pr.id, pr.pattern AS keyword, pr.project_id,
                       pr.enabled, p.name AS project_name
                FROM project_rule pr
                LEFT JOIN project p ON p.id = pr.project_id
                WHERE pr.rule_type = 'keyword'
                ORDER BY pr.pattern COLLATE NOCASE, pr.id
                """
            ).fetchall()
        )
        total_duration_by_project = (
            _project_duration_totals(conn) if include_total_duration else {}
        )

    projects = [
        row
        for row in dict_rows(rows)
        if project_lifecycle_policy.project_visible_in_rules_page(
            row,
            include_system_special=include_system_special,
        )
    ]
    last_used_by_project = {
        int(row["project_id"]): row.get("last_used_at")
        for row in last_used_rows
        if row.get("project_id") is not None
    }
    by_project = {
        int(project["id"]): {
            **project,
            **project_lifecycle_policy.project_rules_capabilities(project),
            "last_used_at": last_used_by_project.get(int(project["id"])),
            "total_duration_seconds": total_duration_by_project.get(
                int(project["id"]), 0
            ),
            "folder_rules": [],
            "keyword_rules": [],
        }
        for project in projects
    }
    for row in folder_rows:
        project = by_project.get(int(row["project_id"]))
        if project is not None:
            project["folder_rules"].append(row)
    for row in keyword_rows:
        project = by_project.get(int(row["project_id"]))
        if project is not None:
            project["keyword_rules"].append(row)
    return list(by_project.values())


def list_project_bindings(include_system_special: bool = True) -> list[dict]:
    """Return the lightweight project/rule catalog without historical projection."""

    return _list_project_bindings(
        include_system_special,
        include_total_duration=False,
    )


def list_project_rule_summaries(
    include_system_special: bool = True,
) -> list[dict]:
    """Return Project Rules page rows with one authoritative all-time projection."""

    return _list_project_bindings(
        include_system_special,
        include_total_duration=True,
    )


def archive_project(project_id: int) -> None:
    with _catalog_uow() as uow:
        conn = uow.connection
        require_mutable_user_project(conn, project_id)
        cursor = conn.execute(
            "UPDATE project SET is_archived = 1, updated_at = ? WHERE id = ?",
            (now_str(), project_id),
        )
        if cursor.rowcount != 1:
            raise ProjectLifecycleError("not_found")
        uow.mark_changed(
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )


def delete_project(project_id: int) -> None:
    soft_delete_project(project_id)


def soft_delete_project(project_id: int) -> None:
    """Tombstone a mutable user project without deleting facts or rules."""

    with _catalog_uow() as uow:
        conn = uow.connection
        require_mutable_user_project(conn, project_id)
        cursor = conn.execute(
            """
            UPDATE project
            SET is_deleted = 1, is_archived = 1, enabled = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (now_str(), project_id),
        )
        if cursor.rowcount != 1:
            raise ProjectLifecycleError("not_found")
        uow.mark_changed(
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )


__all__ = [
    "ProjectLifecycleError",
    "archive_project",
    "create_project",
    "delete_project",
    "get_project",
    "get_project_by_name",
    "is_concrete_project_id",
    "list_active_projects",
    "list_project_bindings",
    "list_project_rule_summaries",
    "list_rule_target_projects",
    "list_selectable_projects",
    "list_user_projects",
    "require_mutable_user_project",
    "set_excluded_project_enabled",
    "set_project_enabled",
    "soft_delete_project",
    "update_project",
]
