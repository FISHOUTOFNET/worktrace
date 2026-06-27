"""Keyword-rule and folder-rule facade for the UI.

Wraps ``rule_service`` (keyword rules) and ``folder_rule_service`` (folder
rules) used by the Project Rules page and the project/rule dialog.
"""

from __future__ import annotations

from typing import Any

from ..services import folder_rule_service, rule_service


class ProjectRuleWriteError(Exception):
    """Stable Project Rules write error for WebView-facing API calls."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _valid_rule_id(rule_id: Any) -> bool:
    return type(rule_id) is int and rule_id > 0


def _valid_enabled(enabled: Any) -> bool:
    return type(enabled) is bool


def _rule_exists(rule_type: str, rule_id: int) -> bool:
    if rule_type == "folder":
        return any(
            int(row.get("id") or 0) == rule_id
            for row in folder_rule_service.list_folder_rules()
        )
    if rule_type == "keyword":
        return any(
            int(row.get("id") or 0) == rule_id
            for row in rule_service.list_rules(include_system=True)
        )
    return False


def set_project_rule_enabled(rule_type: str, rule_id: int, enabled: bool) -> dict[str, Any]:
    """Enable or disable one existing folder/keyword rule.

    This facade is intentionally narrower than the legacy Tkinter API: it
    rejects bool-as-int ids, non-bool enabled values, unknown rule types, and
    missing rules before delegating to the existing service write paths.
    Returned errors are stable codes for the bridge to map to Chinese text.
    """

    if rule_type not in {"folder", "keyword"}:
        return {"ok": False, "error": "invalid_input"}
    if not _valid_rule_id(rule_id) or not _valid_enabled(enabled):
        return {"ok": False, "error": "invalid_input"}
    try:
        if not _rule_exists(rule_type, rule_id):
            return {"ok": False, "error": "not_found"}
        if rule_type == "folder":
            set_folder_rule_enabled(rule_id, enabled)
        else:
            set_keyword_rule_enabled(rule_id, enabled)
        return {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        }
    except ProjectRuleWriteError as exc:
        return {"ok": False, "error": exc.code}
    except Exception:
        return {"ok": False, "error": "operation_failed"}


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
    "ProjectRuleWriteError",
    "preview_folder_rule_conflicts",
    "set_project_rule_enabled",
    "set_folder_rule_enabled",
    "set_keyword_rule_enabled",
]
