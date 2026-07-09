from __future__ import annotations

import time

from ..constants import EXCLUDED_PROJECT, RULE_CACHE_TTL_SECONDS
from ..db import dict_rows, get_connection, get_db_path, now_str
from ..path_utils import (
    is_path_under_folder,
    looks_like_anchor_file_path,
    normalize_folder_key,
    normalize_path_key,
)

_FOLDER_RULE_CACHE_TTL_SECONDS = RULE_CACHE_TTL_SECONDS
_FOLDER_RULE_CACHE: dict[str, tuple[float, list[dict]]] = {}


def invalidate_folder_rule_cache() -> None:
    _FOLDER_RULE_CACHE.pop(str(get_db_path().resolve()), None)


def _enabled_folder_rules() -> list[dict]:
    cache_key = str(get_db_path().resolve())
    now = time.monotonic()
    cached = _FOLDER_RULE_CACHE.get(cache_key)
    if cached is not None and cached[0] >= now:
        return [dict(row) for row in cached[1]]
    with get_connection() as conn:
        rows = conn.execute(
            """
                SELECT fpr.*, p.name AS project_name
                FROM folder_project_rule fpr
                LEFT JOIN project p ON p.id = fpr.project_id
                WHERE fpr.enabled = 1
                  AND COALESCE(p.enabled, 1) = 1
                  AND COALESCE(p.is_archived, 0) = 0
                  AND COALESCE(p.name, '') <> ?
            """,
            (EXCLUDED_PROJECT,),
        ).fetchall()
    rules = dict_rows(rows)
    _FOLDER_RULE_CACHE[cache_key] = (now + _FOLDER_RULE_CACHE_TTL_SECONDS, rules)
    return [dict(row) for row in rules]


def create_or_update_folder_rule(folder_path: str, project_id: int, recursive: bool = True) -> int:
    folder = (folder_path or "").strip()
    if not folder:
        raise ValueError("folder path is required")
    key = normalize_folder_key(folder)
    if not key:
        raise ValueError("folder path is required")
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO folder_project_rule(
                folder_path, normalized_folder_key, project_id, recursive, enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(normalized_folder_key) DO UPDATE SET
                folder_path = excluded.folder_path,
                project_id = excluded.project_id,
                recursive = excluded.recursive,
                enabled = 1,
                updated_at = excluded.updated_at
            """,
            (folder, key, project_id, int(recursive), ts, ts),
        )
        row = conn.execute(
            "SELECT id FROM folder_project_rule WHERE normalized_folder_key = ?",
            (key,),
        ).fetchone()
    invalidate_folder_rule_cache()
    from .privacy_service import clear_exclude_rules_cache
    from .folder_index_service import request_rebuild_for_rule

    clear_exclude_rules_cache()
    rule_id = int(row["id"] if row else cur.lastrowid)
    request_rebuild_for_rule(rule_id)
    return rule_id


def update_folder_rule(rule_id: int, folder_path: str, recursive: bool = True) -> None:
    """Update one existing folder rule's ``folder_path`` and ``recursive`` by id.

    Unlike ``create_or_update_folder_rule``, this preserves the row's ``id``
    even when the new ``folder_path`` produces a different
    ``normalized_folder_key``. ``project_id`` and ``enabled`` are preserved
    as-is; this function does not move a folder rule to a different project
    and does not toggle its enabled state. The folder index for this rule is
    rebuilt because the path may have changed.

    Raises ``ValueError`` if ``folder_path`` is empty or ``rule_id`` does not
    match any row. Raises ``sqlite3.IntegrityError`` (surfaced to the caller
    as ``operation_failed`` by the API facade) if the new normalized key
    already belongs to a different folder rule.
    """
    folder = (folder_path or "").strip()
    if not folder:
        raise ValueError("folder path is required")
    key = normalize_folder_key(folder)
    if not key:
        raise ValueError("folder path is required")
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE folder_project_rule
            SET folder_path = ?,
                normalized_folder_key = ?,
                recursive = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (folder, key, int(recursive), ts, rule_id),
        )
        if cur.rowcount == 0:
            raise ValueError("folder rule not found")
    invalidate_folder_rule_cache()
    from .privacy_service import clear_exclude_rules_cache
    from .folder_index_service import request_rebuild_for_rule

    clear_exclude_rules_cache()
    request_rebuild_for_rule(rule_id)


def delete_folder_rule(rule_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM folder_project_rule WHERE id = ?", (rule_id,))
    invalidate_folder_rule_cache()
    from .privacy_service import clear_exclude_rules_cache
    from .folder_index_service import delete_index_for_rule

    clear_exclude_rules_cache()
    delete_index_for_rule(rule_id)


def set_folder_rule_enabled(rule_id: int, enabled: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE folder_project_rule SET enabled = ?, updated_at = ? WHERE id = ?",
            (int(enabled), now_str(), rule_id),
        )
    invalidate_folder_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()


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


def find_matching_folder_rule(path_or_parent_dir: str) -> dict | None:
    target = (path_or_parent_dir or "").strip()
    if not target:
        return None
    matches = [row for row in _enabled_folder_rules() if _target_matches_rule(target, row)]
    if not matches:
        return None
    return dict(max(matches, key=lambda row: len(row["normalized_folder_key"] or "")))


def preview_folder_rule_conflicts(folder_path: str, project_id: int) -> dict:
    folder = (folder_path or "").strip()
    with get_connection() as conn:
        activity_rows = dict_rows(conn.execute(
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
        ).fetchall())

        rules = dict_rows(conn.execute("SELECT * FROM folder_project_rule").fetchall())
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


def _activity_matches_folder(activity: dict, folder_path: str, recursive: bool = True, rule_id: int | None = None) -> bool:
    # Resource-first: check both resource_path_hint and file_path_hint.
    # A non-anchor resource may store a name-only path_hint (e.g. "floorplan.dwg")
    # while file_path_hint holds the full drive path — check each independently.
    for key in ("resource_path_hint", "file_path_hint"):
        path_hint = str(activity.get(key) or "").strip()
        if path_hint and looks_like_anchor_file_path(path_hint):
            return is_path_under_folder(path_hint, folder_path, recursive)
    # No concrete path: try folder index lookup.
    if rule_id is not None:
        from .folder_index_service import activity_matches_rule_by_index

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
