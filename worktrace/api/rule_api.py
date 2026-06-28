"""Keyword-rule and folder-rule facade for the UI.

Wraps ``rule_service`` (keyword rules) and ``folder_rule_service`` (folder
rules) used by the Project Rules page and the project/rule dialog.
"""

from __future__ import annotations

from typing import Any

from . import project_api
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

    # ``isinstance(rule_type, str)`` short-circuits the set membership check
    # so unhashable non-string types (list / dict) collapse to
    # ``invalid_input`` instead of leaking a ``TypeError`` to the bridge.
    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
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


def create_project_keyword_rule(project_id: Any, keyword: Any) -> dict[str, Any]:
    """Create one new keyword rule on an existing rule-target project.

    Phase 5C narrow WebView-facing facade. It only creates a keyword rule;
    it does not create folder rules, projects, or edit/delete existing
    rules. ``project_id`` must identify a project returned by
    ``project_api.list_rule_target_projects()`` (the same eligibility rule
    the legacy Tkinter dialog uses), so the special local ``排除规则``
    project — which is created with ``enabled = 0`` and is therefore not a
    rule target — is rejected as ``project_not_found`` without bypassing
    the service. The keyword is trimmed before creation and an exact
    duplicate (same ``project_id`` + same trimmed keyword) is rejected as
    ``duplicate_rule``.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``project_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / zero /
      negative) or ``keyword`` is not a real non-empty ``str`` after trim.
    - ``project_not_found`` — the project is not a rule target.
    - ``duplicate_rule`` — an existing keyword rule already binds the same
      keyword to the same project.
    - ``operation_failed`` — any unexpected service failure.
    """

    # ``type(...) is not int`` rejects ``bool`` (since ``type(True) is bool``),
    # ``float``, ``str``, ``None``, and container types in one check.
    if type(project_id) is not int or project_id <= 0:
        return {"ok": False, "error": "invalid_input"}
    if type(keyword) is not str:
        return {"ok": False, "error": "invalid_input"}
    trimmed = keyword.strip()
    if not trimmed:
        return {"ok": False, "error": "invalid_input"}
    try:
        target_ids = {
            int(row.get("id") or 0)
            for row in project_api.list_rule_target_projects()
        }
        if project_id not in target_ids:
            return {"ok": False, "error": "project_not_found"}
        for row in rule_service.list_rules(include_system=True):
            if (
                int(row.get("project_id") or 0) == project_id
                and str(row.get("keyword") or "") == trimmed
            ):
                return {"ok": False, "error": "duplicate_rule"}
        rule_id = rule_service.create_rule(trimmed, project_id)
        return {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": int(rule_id),
                "project_id": int(project_id),
                "keyword": trimmed,
                "enabled": True,
            },
        }
    except ProjectRuleWriteError as exc:
        return {"ok": False, "error": exc.code}
    except Exception:
        return {"ok": False, "error": "operation_failed"}


def delete_project_keyword_rule(rule_id: Any) -> dict[str, Any]:
    """Delete one existing keyword rule.

    Phase 5D narrow WebView-facing facade. It only deletes a keyword rule;
    it does not delete folder rules, projects, or edit/enable/disable any
    rule or project. ``rule_id`` must identify an existing row in
    ``project_rule`` (the keyword rule table). A ``rule_id`` that points at
    a folder rule (``folder_project_rule``) is rejected as ``not_found``
    rather than deleting the folder rule — the keyword delete path must
    never touch folder rules. The facade delegates to the existing
    ``rule_service.delete_rule`` write path, which performs a hard
    ``DELETE FROM project_rule`` and preserves the existing keyword rule
    cache invalidation and privacy exclude cache clearing. No soft-delete
    is invented.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rule_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / tuple /
      set / frozenset / zero / negative).
    - ``not_found`` — no keyword rule exists with this id (covers both
      "id does not exist at all" and "id is a folder rule").
    - ``operation_failed`` — any unexpected service failure.
    """

    # ``type(...) is not int`` rejects ``bool`` (since ``type(True) is bool``),
    # ``float``, ``str``, ``None``, and container types in one check.
    if type(rule_id) is not int or rule_id <= 0:
        return {"ok": False, "error": "invalid_input"}
    try:
        # Reuse the existing existence helper: it only returns True when the
        # id resolves to a row in ``project_rule`` (keyword table). A folder
        # rule id resolves to ``folder_project_rule`` and therefore returns
        # False, so the keyword delete path can never delete a folder rule.
        if not _rule_exists("keyword", rule_id):
            return {"ok": False, "error": "not_found"}
        rule_service.delete_rule(rule_id)
        return {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": int(rule_id),
                "deleted": True,
            },
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
    "create_project_keyword_rule",
    "delete_folder_rule",
    "delete_keyword_rule",
    "delete_project_keyword_rule",
    "ProjectRuleWriteError",
    "preview_folder_rule_conflicts",
    "set_project_rule_enabled",
    "set_folder_rule_enabled",
    "set_keyword_rule_enabled",
]
