from __future__ import annotations

import time

from ..constants import (
    EXCLUDED_PROJECT,
    EXCLUDED_APP_NAME,
    EXCLUDED_PROCESS_NAME,
    EXCLUDED_WINDOW_TITLE,
    STATUS_EXCLUDED,
)
from ..db import dict_rows, get_connection, get_db_path
from ..path_utils import is_path_under_folder, normalize_folder_key, normalize_path_key
from ..platforms.base import ActiveWindow
from ..resource_patterns import infer_resource_identity
from .settings_service import get_list_setting, set_list_setting

_EXCLUDE_KEYWORD_CACHE_TTL_SECONDS = 5.0
_EXCLUDE_KEYWORD_CACHE: dict[str, tuple[float, list[str]]] = {}
_EXCLUDE_RULE_CACHE_TTL_SECONDS = 5.0
_EXCLUDE_RULE_CACHE: dict[str, tuple[float, dict[str, list[dict]]]] = {}


def clear_exclude_keywords_cache() -> None:
    _EXCLUDE_KEYWORD_CACHE.pop(str(get_db_path().resolve()), None)


def clear_exclude_rules_cache() -> None:
    _EXCLUDE_RULE_CACHE.pop(str(get_db_path().resolve()), None)


def get_exclude_keywords() -> list[str]:
    cache_key = str(get_db_path().resolve())
    now = time.monotonic()
    cached = _EXCLUDE_KEYWORD_CACHE.get(cache_key)
    if cached is not None and cached[0] >= now:
        return list(cached[1])
    keywords = get_list_setting("exclude_keywords", [])
    _EXCLUDE_KEYWORD_CACHE[cache_key] = (now + _EXCLUDE_KEYWORD_CACHE_TTL_SECONDS, keywords)
    return list(keywords)


def set_exclude_keywords(keywords: list[str]) -> None:
    cleaned = [item.strip() for item in keywords if item.strip()]
    set_list_setting("exclude_keywords", cleaned)
    _EXCLUDE_KEYWORD_CACHE[str(get_db_path().resolve())] = (
        time.monotonic() + _EXCLUDE_KEYWORD_CACHE_TTL_SECONDS,
        cleaned,
    )


def is_excluded(active_window: ActiveWindow) -> bool:
    haystack = " ".join(
        [
            active_window.app_name,
            active_window.process_name,
            active_window.window_title,
            active_window.file_path_hint or "",
        ]
    ).casefold()
    return (
        _matches_exclude_keyword(haystack)
        or _matches_exclude_file(active_window.file_path_hint)
        or _matches_exclude_folder(active_window.file_path_hint)
    )


def make_excluded_activity_payload() -> dict:
    return {
        "app_name": EXCLUDED_APP_NAME,
        "process_name": EXCLUDED_PROCESS_NAME,
        "window_title": EXCLUDED_WINDOW_TITLE,
        "status": STATUS_EXCLUDED,
        "file_path_hint": None,
    }


def _exclude_rules() -> dict[str, list[dict]]:
    cache_key = str(get_db_path().resolve())
    now = time.monotonic()
    cached = _EXCLUDE_RULE_CACHE.get(cache_key)
    if cached is not None and cached[0] >= now:
        return {
            key: [dict(row) for row in rows]
            for key, rows in cached[1].items()
        }
    with get_connection() as conn:
        project = conn.execute(
            """
            SELECT id, enabled
            FROM project
            WHERE name = ? AND is_archived = 0
            """,
            (EXCLUDED_PROJECT,),
        ).fetchone()
        if not project or not int(project["enabled"] or 0):
            result = {"keywords": [], "files": [], "folders": []}
            _EXCLUDE_RULE_CACHE[cache_key] = (now + _EXCLUDE_RULE_CACHE_TTL_SECONDS, result)
            return result
        project_id = int(project["id"])
        keywords = dict_rows(
            conn.execute(
                """
                SELECT pattern AS keyword
                FROM project_rule
                WHERE project_id = ?
                  AND rule_type = 'keyword'
                  AND enabled = 1
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
        )
        files = dict_rows(
            conn.execute(
                """
                SELECT canonical_key, full_path
                FROM resource
                WHERE default_project_id = ?
                  AND resource_role = 'anchor'
                  AND resource_type = 'file'
                """,
                (project_id,),
            ).fetchall()
        )
        folders = dict_rows(
            conn.execute(
                """
                SELECT folder_path, normalized_folder_key, recursive
                FROM folder_project_rule
                WHERE project_id = ?
                  AND enabled = 1
                ORDER BY length(normalized_folder_key) DESC, id DESC
                """,
                (project_id,),
            ).fetchall()
        )
    result = {"keywords": keywords, "files": files, "folders": folders}
    _EXCLUDE_RULE_CACHE[cache_key] = (now + _EXCLUDE_RULE_CACHE_TTL_SECONDS, result)
    return {
        key: [dict(row) for row in rows]
        for key, rows in result.items()
    }


def _matches_exclude_keyword(haystack: str) -> bool:
    rule_keywords = [
        str(row.get("keyword") or "").strip().casefold()
        for row in _exclude_rules()["keywords"]
    ]
    legacy_keywords = [keyword.casefold() for keyword in get_exclude_keywords()]
    return any(keyword and keyword in haystack for keyword in [*rule_keywords, *legacy_keywords])


def _matches_exclude_file(file_path_hint: str | None) -> bool:
    target = (file_path_hint or "").strip()
    if not target:
        return False
    identity = infer_resource_identity(None, None, None, file_path_hint=target)
    target_key = identity.canonical_key
    target_path_key = normalize_path_key(identity.full_path or target)
    for row in _exclude_rules()["files"]:
        if target_key and row.get("canonical_key") == target_key:
            return True
        if target_path_key and normalize_path_key(str(row.get("full_path") or "")) == target_path_key:
            return True
    return False


def _matches_exclude_folder(file_path_hint: str | None) -> bool:
    target = (file_path_hint or "").strip()
    if not target:
        return False
    target_key = normalize_folder_key(target) or normalize_path_key(target)
    for row in _exclude_rules()["folders"]:
        folder = str(row.get("folder_path") or "")
        if target_key and target_key == str(row.get("normalized_folder_key") or ""):
            return True
        if folder and is_path_under_folder(target, folder, bool(row.get("recursive"))):
            return True
    return False
