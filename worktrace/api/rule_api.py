"""Keyword-rule and folder-rule facade for the UI.

Wraps ``rule_service`` (keyword rules) and ``folder_rule_service`` (folder
rules) used by the Project Rules page and the project/rule dialog.
"""

from __future__ import annotations

from typing import Any

from ..services import folder_rule_service, rule_service


# --- keyword rules -------------------------------------------------------

def create_keyword_rule(keyword: str, project_id: int) -> int:
    return rule_service.create_rule(keyword, project_id)


def set_keyword_rule_enabled(rule_id: int, enabled: bool) -> None:
    rule_service.set_rule_enabled(rule_id, enabled)


def delete_keyword_rule(rule_id: int) -> None:
    rule_service.delete_rule(rule_id)


# --- folder rules --------------------------------------------------------

def create_or_update_folder_rule(folder_path: str, project_id: int, recursive: bool = True) -> int:
    return folder_rule_service.create_or_update_folder_rule(folder_path, project_id, recursive=recursive)


def set_folder_rule_enabled(rule_id: int, enabled: bool) -> None:
    folder_rule_service.set_folder_rule_enabled(rule_id, enabled)


def delete_folder_rule(rule_id: int) -> None:
    folder_rule_service.delete_folder_rule(rule_id)


def preview_folder_rule_conflicts(folder_path: str, project_id: int) -> dict[str, Any]:
    return folder_rule_service.preview_folder_rule_conflicts(folder_path, project_id)


def backfill_folder_rule(rule_id: int, mode: str = "safe") -> dict[str, Any]:
    return folder_rule_service.backfill_folder_rule(rule_id, mode=mode)


__all__ = [
    "backfill_folder_rule",
    "create_keyword_rule",
    "create_or_update_folder_rule",
    "delete_folder_rule",
    "delete_keyword_rule",
    "preview_folder_rule_conflicts",
    "set_folder_rule_enabled",
    "set_keyword_rule_enabled",
]
