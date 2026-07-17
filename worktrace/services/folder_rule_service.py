from __future__ import annotations

import threading

from ..data_generation_repository import DataGenerationNamespace
from ..db import dict_rows, get_connection, get_db_key
from ..generation_clock import generation
from ..path_utils import (
    is_path_under_folder,
    looks_like_anchor_file_path,
    normalize_folder_key,
    normalize_path_key,
)

_FOLDER_RULE_CACHE_LOCK = threading.RLock()
_FOLDER_RULE_CACHE_DATABASE_KEY: str | None = None
_FOLDER_RULE_CACHE_GENERATION: int | None = None
_FOLDER_RULE_CACHE: list[dict] | None = None


def invalidate_folder_rule_cache() -> None:
    """Test/reconfiguration hook; catalog writes invalidate by generation."""

    global _FOLDER_RULE_CACHE_DATABASE_KEY
    global _FOLDER_RULE_CACHE_GENERATION
    global _FOLDER_RULE_CACHE
    with _FOLDER_RULE_CACHE_LOCK:
        _FOLDER_RULE_CACHE_DATABASE_KEY = None
        _FOLDER_RULE_CACHE_GENERATION = None
        _FOLDER_RULE_CACHE = None


def _load_enabled_folder_rules(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT fpr.*, p.name AS project_name, p.enabled AS project_enabled,
               p.is_archived AS project_is_archived,
               p.is_deleted AS project_is_deleted
        FROM folder_project_rule fpr
        LEFT JOIN project p ON p.id = fpr.project_id
        WHERE fpr.enabled = 1
        """
    ).fetchall()
    from . import project_lifecycle_policy

    return [
        row
        for row in dict_rows(rows)
        if project_lifecycle_policy.project_available_for_inference(
            {
                "name": row.get("project_name"),
                "enabled": row.get("project_enabled"),
                "is_archived": row.get("project_is_archived"),
                "is_deleted": row.get("project_is_deleted"),
            }
        )
    ]


def _enabled_folder_rules(conn=None) -> list[dict]:
    if conn is not None:
        return [dict(row) for row in _load_enabled_folder_rules(conn)]

    global _FOLDER_RULE_CACHE_DATABASE_KEY
    global _FOLDER_RULE_CACHE_GENERATION
    global _FOLDER_RULE_CACHE
    while True:
        database_key = get_db_key()
        current_generation = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
        with _FOLDER_RULE_CACHE_LOCK:
            if (
                _FOLDER_RULE_CACHE_DATABASE_KEY == database_key
                and _FOLDER_RULE_CACHE_GENERATION == current_generation
                and _FOLDER_RULE_CACHE is not None
            ):
                return [dict(row) for row in _FOLDER_RULE_CACHE]
        with get_connection() as read_conn:
            rules = _load_enabled_folder_rules(read_conn)
        if generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) != current_generation:
            continue
        with _FOLDER_RULE_CACHE_LOCK:
            _FOLDER_RULE_CACHE_DATABASE_KEY = database_key
            _FOLDER_RULE_CACHE_GENERATION = current_generation
            _FOLDER_RULE_CACHE = [dict(row) for row in rules]
        return [dict(row) for row in rules]


def create_or_update_folder_rule(
    folder_path: str,
    project_id: int,
    recursive: bool = True,
) -> int:
    from .rule_catalog_command_service import create_or_update_folder_rule as command

    return command(folder_path, project_id, recursive)


def update_folder_rule(
    rule_id: int,
    folder_path: str,
    recursive: bool = True,
) -> None:
    from .rule_catalog_command_service import update_folder_rule as command

    if not command(rule_id, folder_path, recursive):
        raise ValueError("folder rule not found")


def delete_folder_rule(rule_id: int) -> bool:
    from .rule_catalog_command_service import delete_folder_rule as command

    return command(rule_id)


def set_folder_rule_enabled(rule_id: int, enabled: bool) -> None:
    from .rule_catalog_command_service import set_folder_rule_enabled as command

    command(rule_id, enabled)


def list_folder_rules() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fpr.*, p.name AS project_name
            FROM folder_project_rule fpr
            LEFT JOIN project p ON p.id = fpr.project_id
            ORDER BY fpr.folder_path COLLATE NOCASE, fpr.id
            """
        ).fetchall()
    return dict_rows(rows)


def find_matching_folder_rule(
    path_or_parent_dir: str,
    *,
    exclude_rule_id: int | None = None,
    conn=None,
) -> dict | None:
    target = (path_or_parent_dir or "").strip()
    if not target:
        return None
    matches = [
        row
        for row in _enabled_folder_rules(conn)
        if _target_matches_rule(target, row)
        and int(row.get("id") or 0) != int(exclude_rule_id or 0)
    ]
    if not matches:
        return None
    return dict(
        max(matches, key=lambda row: len(row["normalized_folder_key"] or ""))
    )


def preview_folder_rule_conflicts(folder_path: str, project_id: int) -> dict:
    folder = (folder_path or "").strip()
    with get_connection() as conn:
        activity_rows = dict_rows(
            conn.execute(
                """
                SELECT
                    a.*,
                    apa.project_id AS effective_project_id,
                    COALESCE(apa.is_manual, 0) AS is_manual,
                    ar.path_hint AS resource_path_hint,
                    ar.is_anchor AS resource_is_anchor
                FROM activity_log a
                LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
                LEFT JOIN activity_resource ar ON ar.activity_id = a.id
                WHERE a.is_deleted = 0
                """
            ).fetchall()
        )
        rules = dict_rows(
            conn.execute("SELECT * FROM folder_project_rule").fetchall()
        )
    child_count = sum(
        1
        for rule in rules
        if int(rule["project_id"]) != int(project_id)
        and is_path_under_folder(rule["folder_path"], folder, recursive=True)
    )
    matching_activities = [
        row for row in activity_rows if _activity_matches_folder(row, folder)
    ]
    return {
        "child_folder_rule_conflicts": child_count,
        "other_project_activity_count": sum(
            1
            for row in matching_activities
            if row.get("effective_project_id") is not None
            and int(row["effective_project_id"]) != int(project_id)
        ),
        "manual_activity_count": sum(
            1
            for row in matching_activities
            if int(row.get("is_manual") or 0)
        ),
    }


def _activity_matches_folder(
    activity: dict,
    folder_path: str,
    recursive: bool = True,
    rule_id: int | None = None,
) -> bool:
    for key in ("resource_path_hint", "file_path_hint"):
        path_hint = str(activity.get(key) or "").strip()
        if path_hint and looks_like_anchor_file_path(path_hint):
            return is_path_under_folder(path_hint, folder_path, recursive)
    if rule_id is not None:
        from .folder_index_query_service import activity_matches_rule_by_index

        return activity_matches_rule_by_index(activity, rule_id)
    return False


def _target_matches_rule(target: str, rule: dict) -> bool:
    folder_path = rule["folder_path"]
    recursive = bool(rule["recursive"])
    if normalize_path_key(target) == normalize_folder_key(folder_path):
        return True
    if looks_like_anchor_file_path(target):
        return is_path_under_folder(target, folder_path, recursive)
    return bool(recursive and is_path_under_folder(target, folder_path, True))
