from __future__ import annotations

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from ..db import dict_rows, get_connection, get_db_path, now_str
from ..mutation_effects import report_structure_mutation
from . import project_lifecycle_policy

_UNCATEGORIZED_PROJECT_IDS: dict[str, int] = {}
_EXCLUDED_PROJECT_IDS: dict[str, int] = {}


def invalidate_uncategorized_project_cache() -> None:
    _UNCATEGORIZED_PROJECT_IDS.pop(str(get_db_path().resolve()), None)
    _EXCLUDED_PROJECT_IDS.pop(str(get_db_path().resolve()), None)


def _normalize_project_language(language: str | None = None) -> str:
    cleaned = (language or "").strip()
    return cleaned or "中文"


@report_structure_mutation
def create_project(name: str, description: str = "", language: str = "中文") -> int:
    name = name.strip()
    if not name:
        raise ValueError("project name is required")
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO project(name, description, language, is_archived, enabled, created_by, created_at, updated_at)
            VALUES (?, ?, ?, 0, 1, 'user', ?, ?)
            """,
            (name, description, _normalize_project_language(language), ts, ts),
        )
        return int(cur.lastrowid)


@report_structure_mutation
def update_project(
    project_id: int,
    name: str,
    description: str = "",
    language: str = "中文",
) -> None:
    project = get_project(project_id)
    if not project:
        raise ValueError("project not found")
    if project.get("created_by") == "system":
        raise ValueError("system project cannot be edited")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("project name is required")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE project
            SET name = ?, description = ?, language = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                cleaned,
                description.strip(),
                _normalize_project_language(language),
                now_str(),
                project_id,
            ),
        )


@report_structure_mutation
def set_project_enabled(project_id: int, enabled: bool) -> None:
    project = get_project(project_id)
    if not project:
        raise ValueError("project not found")
    if project.get("name") == UNCATEGORIZED_PROJECT:
        raise ValueError("uncategorized project cannot be disabled")
    with get_connection() as conn:
        conn.execute(
            "UPDATE project SET enabled = ?, updated_at = ? WHERE id = ?",
            (int(enabled), now_str(), project_id),
        )
    _invalidate_project_lifecycle_caches()


@report_structure_mutation
def set_excluded_project_enabled(enabled: bool) -> int:
    project_id = get_or_create_excluded_project()
    with get_connection() as conn:
        conn.execute(
            "UPDATE project SET enabled = ?, updated_at = ? WHERE id = ? AND name = ?",
            (int(enabled), now_str(), project_id, EXCLUDED_PROJECT),
        )
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()
    return project_id


def get_project(project_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def get_project_by_name(name: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM project WHERE name = ?", (name.strip(),)).fetchone()
    return dict(row) if row else None


def is_concrete_project_id(project_id: int | None) -> bool:
    if not project_id:
        return False
    project = get_project(int(project_id))
    if not project:
        return False
    return project.get("name") not in {UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT}


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
            ORDER BY name COLLATE NOCASE
            """
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
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, name COLLATE NOCASE
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
            """
            SELECT *
            FROM project
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
    return [
        row
        for row in dict_rows(rows)
        if project_lifecycle_policy.project_available_for_rules(row)
    ]


def list_project_bindings(include_system_special: bool = True) -> list[dict]:
    """Return one Project Rules bundle from a single SQLite snapshot."""

    with get_connection() as conn:
        conn.execute("BEGIN")
        rows = conn.execute(
            """
            SELECT *
            FROM project
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, name COLLATE NOCASE
            """,
            (EXCLUDED_PROJECT,),
        ).fetchall()
        last_used_rows = dict_rows(
            conn.execute(
                """
                SELECT apa.project_id AS project_id,
                       MAX(COALESCE(al.end_time, al.start_time)) AS last_used_at
                FROM activity_log al
                LEFT JOIN activity_project_assignment apa ON apa.activity_id = al.id
                WHERE al.is_deleted = 0 AND apa.project_id IS NOT NULL
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
                SELECT pr.id, pr.pattern AS keyword, pr.project_id, pr.enabled,
                       p.name AS project_name
                FROM project_rule pr
                LEFT JOIN project p ON p.id = pr.project_id
                WHERE pr.rule_type = 'keyword'
                ORDER BY pr.pattern COLLATE NOCASE, pr.id
                """
            ).fetchall()
        )
        conn.commit()
    projects = [
        row
        for row in dict_rows(rows)
        if project_lifecycle_policy.project_visible_in_rules_page(
            row, include_system_special=include_system_special
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
            "last_used_at": last_used_by_project.get(int(project["id"])),
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


@report_structure_mutation
def archive_project(project_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE project SET is_archived = 1, updated_at = ? WHERE id = ?",
            (now_str(), project_id),
        )
    _invalidate_project_lifecycle_caches()


def delete_project(project_id: int) -> None:
    soft_delete_project(project_id)


@report_structure_mutation
def soft_delete_project(project_id: int) -> None:
    """Tombstone a project without deleting facts, assignments, rules, or overrides."""

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
        project = dict(row) if row else None
        if not project:
            raise ValueError("project not found")
        if project_lifecycle_policy.project_is_system_or_special(project):
            raise ValueError("system project cannot be deleted")
        cur = conn.execute(
            """
            UPDATE project
            SET is_deleted = 1, is_archived = 1, enabled = 0, updated_at = ?
            WHERE id = ?
            """,
            (now_str(), project_id),
        )
        if cur.rowcount != 1:
            raise ValueError("project not found")
    _invalidate_project_lifecycle_caches()


def _invalidate_project_lifecycle_caches() -> None:
    from .folder_rule_service import invalidate_folder_rule_cache
    from .privacy_service import clear_exclude_rules_cache
    from .project_inference_service import invalidate_keyword_rule_cache

    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()
    clear_exclude_rules_cache()


def get_or_create_uncategorized_project(*, conn=None) -> int:
    """Return the bootstrap-owned uncategorized project without creating it."""

    return _require_system_project_id(
        UNCATEGORIZED_PROJECT,
        _UNCATEGORIZED_PROJECT_IDS,
        conn=conn,
    )


def get_or_create_excluded_project() -> int:
    """Return the bootstrap-owned excluded project without creating it."""

    return _require_system_project_id(EXCLUDED_PROJECT, _EXCLUDED_PROJECT_IDS)


def _require_system_project_id(
    name: str,
    cache: dict[str, int],
    *,
    conn=None,
) -> int:
    cache_key = str(get_db_path().resolve())
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    if conn is not None:
        row = conn.execute("SELECT id FROM project WHERE name = ?", (name,)).fetchone()
    else:
        with get_connection() as read_conn:
            row = read_conn.execute(
                "SELECT id FROM project WHERE name = ?",
                (name,),
            ).fetchone()
    if row is None:
        raise ValueError("database_schema_incompatible")
    project_id = int(row["id"])
    cache[cache_key] = project_id
    return project_id
