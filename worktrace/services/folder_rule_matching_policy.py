"""Pure canonical matching policy shared by folder-rule consumers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..path_utils import (
    is_path_under_folder,
    looks_like_anchor_file_path,
    normalize_folder_key,
    normalize_path_key,
)


def target_matches_rule(target: str, rule: Mapping[str, object]) -> bool:
    value = str(target or "").strip()
    folder_path = str(rule.get("folder_path") or "").strip()
    if not value or not folder_path:
        return False
    recursive = bool(int(rule.get("recursive") or 0))
    if normalize_path_key(value) == normalize_folder_key(folder_path):
        return True
    if looks_like_anchor_file_path(value):
        return is_path_under_folder(value, folder_path, recursive)
    return bool(recursive and is_path_under_folder(value, folder_path, True))


def select_automatic_rule(
    target: str,
    rules: Iterable[Mapping[str, object]],
    *,
    exclude_rule_id: int | None = None,
) -> dict | None:
    """Select the single canonical automatic rule for a concrete target."""

    excluded_id = int(exclude_rule_id or 0)
    matches = [
        dict(rule)
        for rule in rules
        if int(rule.get("id") or rule.get("folder_rule_id") or 0) != excluded_id
        and target_matches_rule(target, rule)
    ]
    if not matches:
        return None
    return max(matches, key=_precedence_key)


def select_automatic_indexed_rule(
    candidates: Iterable[Mapping[str, object]],
) -> dict | None:
    """Resolve indexed filename candidates without guessing across projects."""

    by_path: dict[str, list[dict]] = {}
    for candidate in candidates:
        row = dict(candidate)
        path = str(row.get("file_path") or "").strip()
        if not path:
            continue
        path_key = str(row.get("normalized_path_key") or normalize_path_key(path))
        by_path.setdefault(path_key, []).append(row)
    selected = [
        rule
        for rows in by_path.values()
        if (rule := select_automatic_rule(str(rows[0]["file_path"]), rows))
        is not None
    ]
    if not selected:
        return None
    if len({int(rule.get("project_id") or 0) for rule in selected}) != 1:
        return None
    return max(selected, key=_precedence_key)


def rule_is_candidate(
    rule_id: int,
    candidates: Iterable[Mapping[str, object]],
) -> bool:
    """Honor a user's explicit history rule when it actually matched."""

    requested = int(rule_id)
    return any(
        int(candidate.get("id") or candidate.get("folder_rule_id") or 0)
        == requested
        and target_matches_rule(
            str(candidate.get("file_path") or ""),
            candidate,
        )
        for candidate in candidates
    )


def _precedence_key(rule: Mapping[str, object]) -> tuple[int, int]:
    normalized = str(rule.get("normalized_folder_key") or "")
    return (len(normalized), int(rule.get("id") or rule.get("folder_rule_id") or 0))


__all__ = [
    "rule_is_candidate",
    "select_automatic_indexed_rule",
    "select_automatic_rule",
    "target_matches_rule",
]
