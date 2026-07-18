"""Pure read model for the durable folder-rule file index.

This module reads only the active durable index generation. It never consults
the live filesystem, marks entries stale, requests rebuilds, or mutates index
state. Filesystem validation belongs to the maintenance worker so one published
index generation always produces deterministic query results.
"""

from __future__ import annotations

from ..constants import EXCLUDED_PROJECT
from ..db import dict_rows, get_connection
from ..path_utils import normalize_path_key
from ..resources.title_parsing import extract_file_name_from_title, normalize_file_name
from . import folder_rule_matching_policy


def _normalize_index_file_name(value: str | None) -> str:
    return normalize_file_name(str(value or ""))


def lookup_indexed_paths_for_file_name(
    file_name: str | None,
    activity_start_time: str | None = None,
    *,
    include_excluded: bool = False,
    conn=None,
) -> list[dict]:
    """Return rows from the currently published durable index snapshot."""

    normalized = _normalize_index_file_name(file_name)
    if not normalized:
        return []
    project_clause = "" if include_excluded else "AND p.name <> ?"
    time_clause = "AND state.valid_from <= ?" if activity_start_time else ""
    params: list[object] = [normalized]
    if not include_excluded:
        params.append(EXCLUDED_PROJECT)
    if activity_start_time:
        params.append(activity_start_time)
    sql = f"""
        SELECT idx.folder_rule_id, idx.file_name, idx.file_path,
               idx.normalized_path_key, state.valid_from, state.active_generation,
               fpr.id AS id, fpr.folder_path, fpr.normalized_folder_key,
               fpr.recursive, fpr.project_id,
               p.name AS project_name
        FROM folder_rule_file_index idx
        JOIN folder_rule_index_state state
          ON state.folder_rule_id = idx.folder_rule_id
         AND state.active_generation = idx.generation
        JOIN folder_project_rule fpr ON fpr.id = idx.folder_rule_id
        JOIN project p ON p.id = fpr.project_id
        WHERE idx.normalized_file_name = ?
          AND state.active_generation IS NOT NULL
          AND state.valid_from IS NOT NULL
          AND fpr.enabled = 1
          AND p.enabled = 1
          AND COALESCE(p.is_archived, 0) = 0
          AND COALESCE(p.is_deleted, 0) = 0
          {project_clause}
          {time_clause}
        ORDER BY length(fpr.normalized_folder_key) DESC, idx.id ASC
    """
    if conn is None:
        with get_connection() as read_conn:
            rows = dict_rows(read_conn.execute(sql, params).fetchall())
    else:
        rows = dict_rows(conn.execute(sql, params).fetchall())
    results: dict[str, dict] = {}
    for row in rows:
        path = str(row.get("file_path") or "").strip()
        if not path or not folder_rule_matching_policy.target_matches_rule(path, row):
            continue
        key = str(row.get("normalized_path_key") or normalize_path_key(path))
        results.setdefault(key, row)
    return list(results.values())


def resolve_unique_path_from_title(
    window_title: str | None,
    activity_start_time: str | None = None,
    *,
    include_excluded: bool = True,
    conn=None,
) -> str | None:
    file_name = extract_file_name_from_title(window_title)
    if not file_name:
        return None
    candidates = lookup_indexed_paths_for_file_name(
        file_name,
        activity_start_time,
        include_excluded=include_excluded,
        conn=conn,
    )
    if len(candidates) != 1:
        return None
    return str(candidates[0]["file_path"])


def find_matching_folder_rule_for_file_name(
    file_name: str | None,
    activity_start_time: str | None = None,
    *,
    conn=None,
) -> dict | None:
    candidates = lookup_indexed_paths_for_file_name(
        file_name,
        activity_start_time,
        include_excluded=False,
        conn=conn,
    )
    if not candidates:
        return None
    return folder_rule_matching_policy.select_automatic_indexed_rule(candidates)


__all__ = [
    "find_matching_folder_rule_for_file_name",
    "lookup_indexed_paths_for_file_name",
    "resolve_unique_path_from_title",
]
