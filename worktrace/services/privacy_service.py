from __future__ import annotations

import time

from ..constants import (
    EXCLUDED_PROJECT,
    EXCLUDED_APP_NAME,
    EXCLUDED_PROCESS_NAME,
    EXCLUDED_WINDOW_TITLE,
    RULE_CACHE_TTL_SECONDS,
    STATUS_EXCLUDED,
)
from ..db import dict_rows, get_connection, get_db_path
from ..path_utils import is_path_under_folder, normalize_folder_key, normalize_path_key
from ..platforms.base import ActiveWindow

_EXCLUDE_RULE_CACHE_TTL_SECONDS = RULE_CACHE_TTL_SECONDS
_EXCLUDE_RULE_CACHE: dict[str, tuple[float, dict[str, list[dict]]]] = {}


def clear_exclude_rules_cache() -> None:
    _EXCLUDE_RULE_CACHE.pop(str(get_db_path().resolve()), None)


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
        or _matches_exclude_folder(active_window.file_path_hint)
        or _matches_indexed_exclude_folder(active_window.window_title)
    )


def is_resource_excluded(resource) -> bool:
    """Return True if a DetectedResource (or dict) should be excluded."""
    if resource is None:
        return False
    if isinstance(resource, dict):
        fields = [
            str(resource.get("app_name") or ""),
            str(resource.get("process_name") or ""),
            str(resource.get("window_title") or ""),
            str(resource.get("path_hint") or ""),
            str(resource.get("uri_host") or ""),
            str(resource.get("uri_hint") or ""),
            str(resource.get("display_name") or ""),
            str(resource.get("identity_key") or ""),
        ]
        metadata_raw = resource.get("metadata_json")
        if metadata_raw:
            fields.append(str(metadata_raw))
        resource_path = resource.get("path_hint")
    else:
        fields = [
            resource.app_name or "",
            resource.process_name or "",
            resource.window_title or "",
            resource.path_hint or "",
            resource.uri_host or "",
            resource.uri_hint or "",
            resource.display_name or "",
            resource.identity_key or "",
        ]
        if resource.metadata_json:
            fields.append(resource.metadata_json)
        resource_path = resource.path_hint
    haystack = " ".join(fields).casefold()
    if _matches_exclude_keyword(haystack):
        return True
    return _matches_exclude_folder(resource_path)


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
            result = {"keywords": [], "folders": []}
            _EXCLUDE_RULE_CACHE[cache_key] = (
                now + _EXCLUDE_RULE_CACHE_TTL_SECONDS,
                result,
            )
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
    result = {"keywords": keywords, "folders": folders}
    _EXCLUDE_RULE_CACHE[cache_key] = (
        now + _EXCLUDE_RULE_CACHE_TTL_SECONDS,
        result,
    )
    return {
        key: [dict(row) for row in rows]
        for key, rows in result.items()
    }


def _matches_exclude_keyword(haystack: str) -> bool:
    rule_keywords = [
        str(row.get("keyword") or "").strip().casefold()
        for row in _exclude_rules()["keywords"]
    ]
    return any(keyword and keyword in haystack for keyword in rule_keywords)


def _matches_exclude_folder(file_path_hint: str | None) -> bool:
    target = (file_path_hint or "").strip()
    if not target:
        return False
    target_key = normalize_folder_key(target) or normalize_path_key(target)
    for row in _exclude_rules()["folders"]:
        folder = str(row.get("folder_path") or "")
        if target_key and target_key == str(row.get("normalized_folder_key") or ""):
            return True
        if folder and is_path_under_folder(
            target,
            folder,
            bool(row.get("recursive")),
        ):
            return True
    return False


def _matches_indexed_exclude_folder(window_title: str | None) -> bool:
    if not (window_title or "").strip():
        return False
    from .folder_index_service import resolve_unique_path_from_title

    # Deliberately allow database/index failures to propagate.  The collector
    # treats privacy-evaluation errors as a failed observation and therefore
    # never persists real metadata on an uncertain decision.
    path = resolve_unique_path_from_title(
        window_title,
        include_excluded=True,
    )
    return _matches_exclude_folder(path)
