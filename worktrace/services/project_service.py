from __future__ import annotations

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from ..db import dict_rows, get_connection, get_db_path, now_str

_UNCATEGORIZED_PROJECT_IDS: dict[str, int] = {}
_EXCLUDED_PROJECT_IDS: dict[str, int] = {}


def invalidate_uncategorized_project_cache() -> None:
    _UNCATEGORIZED_PROJECT_IDS.pop(str(get_db_path().resolve()), None)
    _EXCLUDED_PROJECT_IDS.pop(str(get_db_path().resolve()), None)


def _normalize_project_language(language: str | None = None) -> str:
    cleaned = (language or "").strip()
    return cleaned or "中文"


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
    from .folder_rule_service import invalidate_folder_rule_cache
    from .privacy_service import clear_exclude_rules_cache
    from .project_inference_service import invalidate_keyword_rule_cache

    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()
    clear_exclude_rules_cache()


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
              AND enabled = 1
              AND (created_by = 'user' OR name = ?)
              AND name <> ?
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, name COLLATE NOCASE
            """,
            (UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT),
        ).fetchall()
    return dict_rows(rows)


def list_rule_target_projects() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project
            WHERE is_archived = 0
              AND enabled = 1
              AND created_by = 'user'
              AND name <> ?
            ORDER BY name COLLATE NOCASE
            """,
            (EXCLUDED_PROJECT,),
        ).fetchall()
    return dict_rows(rows)


def list_project_bindings(include_system_special: bool = True) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project
            WHERE is_archived = 0
              AND (
                    created_by = 'user'
                    OR (? = 1 AND name = ?)
              )
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, name COLLATE NOCASE
            """,
            (int(include_system_special), EXCLUDED_PROJECT, EXCLUDED_PROJECT),
        ).fetchall()
    projects = dict_rows(rows)
    with get_connection() as conn:
        last_used_rows = dict_rows(
            conn.execute(
                """
                SELECT
                    COALESCE(apa.project_id, al.project_id) AS project_id,
                    MAX(COALESCE(al.end_time, al.start_time)) AS last_used_at
                FROM activity_log al
                LEFT JOIN activity_project_assignment apa
                    ON apa.activity_id = al.id
                WHERE al.is_deleted = 0
                  AND COALESCE(apa.project_id, al.project_id) IS NOT NULL
                GROUP BY COALESCE(apa.project_id, al.project_id)
                """
            ).fetchall()
        )
    last_used_by_project = {
        int(row["project_id"]): row.get("last_used_at")
        for row in last_used_rows
        if row.get("project_id") is not None
    }
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


def archive_project(project_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE project SET is_archived = 1, updated_at = ? WHERE id = ?",
            (now_str(), project_id),
        )
    # Archiving removes the project from rule target / selectable / active
    # lists, so the folder rule, keyword rule, and privacy exclude caches
    # must be invalidated to avoid stale state. Mirrors set_project_enabled.
    from .folder_rule_service import invalidate_folder_rule_cache
    from .privacy_service import clear_exclude_rules_cache
    from .project_inference_service import invalidate_keyword_rule_cache

    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()
    clear_exclude_rules_cache()


def delete_project(project_id: int) -> None:
    project = get_project(project_id)
    if not project:
        raise ValueError("project not found")
    if project.get("created_by") == "system" or project.get("name") == UNCATEGORIZED_PROJECT:
        raise ValueError("system project cannot be deleted")
    with get_connection() as conn:
        conn.execute("DELETE FROM folder_project_rule WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM project_rule WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM project WHERE id = ?", (project_id,))
    from .folder_rule_service import invalidate_folder_rule_cache
    from .project_inference_service import invalidate_keyword_rule_cache

    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()


def get_or_create_uncategorized_project() -> int:
    cache_key = str(get_db_path().resolve())
    cached = _UNCATEGORIZED_PROJECT_IDS.get(cache_key)
    if cached is not None:
        return cached
    ts = now_str()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()
        if row:
            project_id = int(row["id"])
            _UNCATEGORIZED_PROJECT_IDS[cache_key] = project_id
            return project_id
        cur = conn.execute(
            """
            INSERT INTO project(name, description, language, is_archived, enabled, created_by, created_at, updated_at)
            VALUES (?, '', '中文', 0, 1, 'system', ?, ?)
            """,
            (UNCATEGORIZED_PROJECT, ts, ts),
        )
        project_id = int(cur.lastrowid)
        _UNCATEGORIZED_PROJECT_IDS[cache_key] = project_id
        return project_id


def get_or_create_excluded_project() -> int:
    cache_key = str(get_db_path().resolve())
    cached = _EXCLUDED_PROJECT_IDS.get(cache_key)
    if cached is not None:
        return cached
    ts = now_str()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM project WHERE name = ?", (EXCLUDED_PROJECT,)).fetchone()
        if row:
            project_id = int(row["id"])
            _EXCLUDED_PROJECT_IDS[cache_key] = project_id
            return project_id
        cur = conn.execute(
            """
            INSERT INTO project(name, description, language, is_archived, enabled, created_by, created_at, updated_at)
            VALUES (?, '命中后匿名记录', '中文', 0, 0, 'system', ?, ?)
            """,
            (EXCLUDED_PROJECT, ts, ts),
        )
        project_id = int(cur.lastrowid)
        _EXCLUDED_PROJECT_IDS[cache_key] = project_id
        return project_id
