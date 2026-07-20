from __future__ import annotations

import threading
from dataclasses import dataclass

from ..constants import (
    EXCLUDED_APP_NAME,
    EXCLUDED_PROCESS_NAME,
    EXCLUDED_PROJECT,
    EXCLUDED_WINDOW_TITLE,
    STATUS_EXCLUDED,
)
from ..data_generation_repository import DataGenerationNamespace
from ..db import dict_rows, get_connection, get_db_key
from ..generation_clock import generation_tuple
from ..path_utils import (
    is_path_under_folder,
    normalize_folder_key,
    normalize_path_key,
)
from ..platforms.base import ActiveWindow
from ..resources.title_parsing import extract_file_name_from_title

_EXCLUDE_RULE_CACHE_LOCK = threading.RLock()
_EXCLUDE_RULE_CACHE_DATABASE_KEY: str | None = None
_EXCLUDE_RULE_CACHE_GENERATION: tuple[int, int] | None = None
_EXCLUDE_RULE_CACHE: dict[str, list[dict]] | None = None
_EXCLUDE_RULE_CACHE_NAMESPACES = (
    DataGenerationNamespace.PRIVACY_CATALOG,
    DataGenerationNamespace.DATABASE_REPLACEMENT,
)


class PrivacyResolutionPending(RuntimeError):
    """A privacy-sensitive local-file window cannot yet be classified safely."""


@dataclass(frozen=True)
class ExclusionDecision:
    excluded: bool
    resolution_pending: bool
    refresh_required: bool


def clear_exclude_rules_cache() -> None:
    """Test/reconfiguration hook; privacy writes invalidate by generation."""

    global _EXCLUDE_RULE_CACHE_DATABASE_KEY
    global _EXCLUDE_RULE_CACHE_GENERATION
    global _EXCLUDE_RULE_CACHE
    with _EXCLUDE_RULE_CACHE_LOCK:
        _EXCLUDE_RULE_CACHE_DATABASE_KEY = None
        _EXCLUDE_RULE_CACHE_GENERATION = None
        _EXCLUDE_RULE_CACHE = None


def evaluate_exclusion(
    active_window: ActiveWindow,
    *,
    conn=None,
) -> ExclusionDecision:
    """Pure exclusion query; it never schedules maintenance or writes SQLite."""

    haystack = " ".join(
        [
            active_window.app_name,
            active_window.process_name,
            active_window.window_title,
            active_window.file_path_hint or "",
        ]
    ).casefold()
    if _matches_exclude_keyword(haystack, conn=conn):
        return ExclusionDecision(True, False, False)
    authoritative_path = str(active_window.file_path_hint or "").strip()
    if authoritative_path:
        return ExclusionDecision(
            _matches_exclude_folder(authoritative_path, conn=conn),
            False,
            False,
        )

    folder_rules = _exclude_rules(conn=conn)["folders"]
    if not folder_rules:
        return ExclusionDecision(False, False, False)
    file_name = extract_file_name_from_title(active_window.window_title)
    if file_name:
        from .folder_index_query_service import lookup_indexed_paths_for_file_name

        candidates = lookup_indexed_paths_for_file_name(
            file_name,
            active_window.activity_start_time,
            include_excluded=True,
            conn=conn,
        )
        if any(
            _matches_exclude_folder(
                str(candidate.get("file_path") or ""),
                conn=conn,
            )
            for candidate in candidates
        ):
            return ExclusionDecision(True, False, False)

    if active_window.privacy_path_required:
        return ExclusionDecision(True, True, True)
    return ExclusionDecision(False, False, False)


def is_excluded(active_window: ActiveWindow, *, conn=None) -> bool:
    """Compatibility query wrapper with no implicit write capability."""

    decision = evaluate_exclusion(active_window, conn=conn)
    if decision.resolution_pending:
        raise PrivacyResolutionPending("privacy_path_unresolved")
    return decision.excluded


def is_resource_excluded(resource, *, conn=None) -> bool:
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
    if _matches_exclude_keyword(haystack, conn=conn):
        return True
    return _matches_exclude_folder(resource_path, conn=conn)


def make_excluded_activity_payload() -> dict:
    return {
        "app_name": EXCLUDED_APP_NAME,
        "process_name": EXCLUDED_PROCESS_NAME,
        "window_title": EXCLUDED_WINDOW_TITLE,
        "status": STATUS_EXCLUDED,
        "file_path_hint": None,
    }


def _load_exclude_rules(conn) -> dict[str, list[dict]]:
    project = conn.execute(
        """
        SELECT id, enabled
        FROM project
        WHERE name = ? AND is_archived = 0
        """,
        (EXCLUDED_PROJECT,),
    ).fetchone()
    if not project or not int(project["enabled"] or 0):
        return {"keywords": [], "folders": []}
    project_id = int(project["id"])
    return {
        "keywords": dict_rows(
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
        ),
        "folders": dict_rows(
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
        ),
    }


def _copy_rule_snapshot(value: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {key: [dict(row) for row in rows] for key, rows in value.items()}


def _exclude_rules(*, conn=None) -> dict[str, list[dict]]:
    global _EXCLUDE_RULE_CACHE_DATABASE_KEY
    global _EXCLUDE_RULE_CACHE_GENERATION
    global _EXCLUDE_RULE_CACHE
    if conn is not None:
        return _load_exclude_rules(conn)
    while True:
        database_key = get_db_key()
        current_generation = generation_tuple(_EXCLUDE_RULE_CACHE_NAMESPACES)
        with _EXCLUDE_RULE_CACHE_LOCK:
            if (
                _EXCLUDE_RULE_CACHE_DATABASE_KEY == database_key
                and _EXCLUDE_RULE_CACHE_GENERATION == current_generation
                and _EXCLUDE_RULE_CACHE is not None
            ):
                return _copy_rule_snapshot(_EXCLUDE_RULE_CACHE)
        with get_connection() as read_conn:
            result = _load_exclude_rules(read_conn)
        if generation_tuple(_EXCLUDE_RULE_CACHE_NAMESPACES) != current_generation:
            continue
        with _EXCLUDE_RULE_CACHE_LOCK:
            _EXCLUDE_RULE_CACHE_DATABASE_KEY = database_key
            _EXCLUDE_RULE_CACHE_GENERATION = current_generation
            _EXCLUDE_RULE_CACHE = _copy_rule_snapshot(result)
        return _copy_rule_snapshot(result)


def _matches_exclude_keyword(haystack: str, *, conn=None) -> bool:
    rule_keywords = [
        str(row.get("keyword") or "").strip().casefold()
        for row in _exclude_rules(conn=conn)["keywords"]
    ]
    return any(keyword and keyword in haystack for keyword in rule_keywords)


def _matches_exclude_folder(file_path_hint: str | None, *, conn=None) -> bool:
    target = (file_path_hint or "").strip()
    if not target:
        return False
    target_key = normalize_folder_key(target) or normalize_path_key(target)
    for row in _exclude_rules(conn=conn)["folders"]:
        folder = str(row.get("folder_path") or "")
        if target_key and target_key == str(
            row.get("normalized_folder_key") or ""
        ):
            return True
        if folder and is_path_under_folder(
            target,
            folder,
            bool(row.get("recursive")),
        ):
            return True
    return False


__all__ = [
    "ExclusionDecision",
    "PrivacyResolutionPending",
    "clear_exclude_rules_cache",
    "evaluate_exclusion",
    "is_excluded",
    "is_resource_excluded",
    "make_excluded_activity_payload",
]
