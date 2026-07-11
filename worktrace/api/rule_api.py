"""Keyword-rule and folder-rule facade for the UI.

Wraps ``rule_service`` (keyword rules) and ``folder_rule_service`` (folder
rules) used by the Project Rules page and the project/rule dialog.

Shared write-path validation / fail / success payloads come from
``worktrace.api._write_contract`` so every Project Rules facade uses the
same "true positive int", "true bool", "true non-empty str", and stable
``{"ok": False, "error": code}`` / ``{"ok": True, ...}`` shapes.

Keyword-only operations never touch folder rules and never create projects
or folders unless the function is explicitly a project lifecycle facade.
"""

from __future__ import annotations

from typing import Any

from . import project_api
from ._write_contract import (
    ERROR_DUPLICATE_RULE,
    ERROR_INVALID_INPUT,
    ERROR_NOT_FOUND,
    ERROR_OPERATION_FAILED,
    ERROR_PROJECT_NOT_AVAILABLE,
    ERROR_PROJECT_NOT_FOUND,
    ERROR_RULE_DISABLED,
    ERROR_TOO_MANY_MATCHES,
    ERROR_TOO_MANY_RULES,
    fail_payload,
    ok_payload,
    valid_bool,
    valid_int,
    valid_nonempty_str,
)
from ..services import folder_rule_service, project_service, rule_service

_APPLY_TO_HISTORY_UNSET = object()


class ProjectRuleWriteError(Exception):
    """Stable Project Rules write error for WebView-facing API calls."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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

    Rejects bool-as-int ids, non-bool enabled values, unknown rule types,
    and missing rules before delegating to the existing service write paths.
    Returned errors are stable codes for bridge-side Chinese messages.
    """

    # ``isinstance(rule_type, str)`` short-circuits the set membership check
    # so unhashable non-string types (list / dict) collapse to
    # ``invalid_input`` instead of leaking a ``TypeError`` to the bridge.
    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_int(rule_id) or not valid_bool(enabled):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        if not _rule_exists(rule_type, rule_id):
            return fail_payload(ERROR_NOT_FOUND)
        if rule_type == "folder":
            set_folder_rule_enabled(rule_id, enabled)
        else:
            set_keyword_rule_enabled(rule_id, enabled)
        return ok_payload(
            rule_type=rule_type,
            rule_id=rule_id,
            enabled=enabled,
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def create_project_keyword_rule(project_id: Any, keyword: Any) -> dict[str, Any]:
    """Create one new keyword rule on an existing rule-target project."""

    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed = valid_nonempty_str(keyword)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        target_ids = {
            int(row.get("id") or 0)
            for row in project_api.list_rule_target_projects()
        }
        if project_id not in target_ids:
            return fail_payload(ERROR_PROJECT_NOT_FOUND)
        for row in rule_service.list_rules(include_system=True):
            if (
                int(row.get("project_id") or 0) == project_id
                and str(row.get("keyword") or "") == trimmed
            ):
                return fail_payload(ERROR_DUPLICATE_RULE)
        rule_id = rule_service.create_rule(trimmed, project_id)
        return ok_payload(
            rule={
                "kind": "keyword",
                "id": int(rule_id),
                "project_id": int(project_id),
                "keyword": trimmed,
                "enabled": True,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def delete_project_keyword_rule(rule_id: Any, apply_to_history: Any = _APPLY_TO_HISTORY_UNSET) -> dict[str, Any]:
    """Delete one existing keyword rule."""

    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    if apply_to_history is not _APPLY_TO_HISTORY_UNSET and not valid_bool(apply_to_history):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        # Reuse the existing existence helper: it only returns True when the
        # id resolves to a row in ``project_rule`` (keyword table). A folder
        # rule id resolves to ``folder_project_rule`` and therefore returns
        # False, so the keyword delete path can never delete a folder rule.
        if not _rule_exists("keyword", rule_id):
            return fail_payload(ERROR_NOT_FOUND)
        explicit_history_choice = apply_to_history is not _APPLY_TO_HISTORY_UNSET
        apply_to_history = False if not explicit_history_choice else apply_to_history
        history_result = {"updated_count": 0}
        if apply_to_history:
            from ..services import rule_history_application_service
            history_result = rule_history_application_service.remove_rule_from_history("keyword", rule_id)
        rule_service.delete_rule(rule_id)
        from ..services import context_service
        context_service.invalidate_context_recompute_cache()
        rule = {"kind": "keyword", "id": int(rule_id), "deleted": True}
        if explicit_history_choice:
            rule.update({"history_updated": bool(apply_to_history), "updated_count": int(history_result.get("updated_count") or 0)})
        return ok_payload(rule=rule)
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)




def _keyword_rule_row(rule_id: int) -> dict | None:
    """Return the keyword rule row for ``rule_id`` or ``None`` if absent.

    Only resolves ids in the ``project_rule`` table; folder rule ids return
    ``None`` so the keyword edit path can never touch folder rules.
    """
    for row in rule_service.list_rules(include_system=True):
        if int(row.get("id") or 0) == rule_id:
            return dict(row)
    return None


def update_project_keyword_rule(rule_id: Any, keyword: Any) -> dict[str, Any]:
    """Update one existing keyword rule's ``keyword`` text."""

    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed = valid_nonempty_str(keyword)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        # ``_keyword_rule_row`` only resolves ids in ``project_rule``; a
        # folder rule id resolves to ``None`` and therefore returns
        # ``not_found``, so the keyword edit path can never modify a folder
        # rule.
        existing = _keyword_rule_row(rule_id)
        if existing is None:
            return fail_payload(ERROR_NOT_FOUND)
        project_id = int(existing.get("project_id") or 0)
        enabled = bool(int(existing.get("enabled") or 0))
        # Duplicate check: reject if another keyword rule in the same
        # project already binds the same trimmed keyword. The rule being
        # updated is excluded so updating to its own current keyword
        # succeeds. Different projects may share the same keyword.
        for row in rule_service.list_rules(include_system=True):
            if (
                int(row.get("project_id") or 0) == project_id
                and str(row.get("keyword") or "") == trimmed
                and int(row.get("id") or 0) != rule_id
            ):
                return fail_payload(ERROR_DUPLICATE_RULE)
        rule_service.update_rule(rule_id, trimmed)
        return ok_payload(
            rule={
                "kind": "keyword",
                "id": int(rule_id),
                "project_id": project_id,
                "keyword": trimmed,
                "enabled": enabled,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)




def _folder_rule_row(rule_id: int) -> dict | None:
    """Return the folder rule row for ``rule_id`` or ``None`` if absent.

    Only resolves ids in the ``folder_project_rule`` table; keyword rule ids
    return ``None`` so the folder CRUD paths can never touch keyword rules.
    """
    for row in folder_rule_service.list_folder_rules():
        if int(row.get("id") or 0) == rule_id:
            return dict(row)
    return None


def create_project_folder_rule(
    project_id: Any, folder_path: Any, recursive: Any
) -> dict[str, Any]:
    """Create one new folder rule on an existing rule-target project."""

    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed = valid_nonempty_str(folder_path)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_bool(recursive):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        target_ids = {
            int(row.get("id") or 0)
            for row in project_api.list_rule_target_projects()
        }
        if project_id not in target_ids:
            return fail_payload(ERROR_PROJECT_NOT_FOUND)
        rule_id = folder_rule_service.create_or_update_folder_rule(
            trimmed, project_id, recursive=recursive
        )
        return ok_payload(
            rule={
                "kind": "folder",
                "id": int(rule_id),
                "project_id": int(project_id),
                "folder_path": trimmed,
                "recursive": bool(recursive),
                "enabled": True,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def update_project_folder_rule(
    rule_id: Any, folder_path: Any, recursive: Any
) -> dict[str, Any]:
    """Update one existing folder rule's ``folder_path`` and ``recursive``."""

    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed = valid_nonempty_str(folder_path)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_bool(recursive):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        # ``_folder_rule_row`` only resolves ids in ``folder_project_rule``;
        # a keyword rule id resolves to ``None`` and therefore returns
        # ``not_found``, so the folder update path can never modify a
        # keyword rule.
        existing = _folder_rule_row(rule_id)
        if existing is None:
            return fail_payload(ERROR_NOT_FOUND)
        # invalidation / privacy exclude cache clearing / folder index
        project_id = int(existing.get("project_id") or 0)
        enabled = bool(int(existing.get("enabled") or 0))
        folder_rule_service.update_folder_rule(
            rule_id, trimmed, recursive=recursive
        )
        return ok_payload(
            rule={
                "kind": "folder",
                "id": int(rule_id),
                "project_id": project_id,
                "folder_path": trimmed,
                "recursive": bool(recursive),
                "enabled": enabled,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def delete_project_folder_rule(rule_id: Any, apply_to_history: Any = _APPLY_TO_HISTORY_UNSET) -> dict[str, Any]:
    """Delete one existing folder rule."""

    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    if apply_to_history is not _APPLY_TO_HISTORY_UNSET and not valid_bool(apply_to_history):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        # ``_folder_rule_row`` only resolves ids in ``folder_project_rule``;
        # a keyword rule id resolves to ``None`` and therefore returns
        # ``not_found``, so the folder delete path can never delete a
        # keyword rule.
        if _folder_rule_row(rule_id) is None:
            return fail_payload(ERROR_NOT_FOUND)
        explicit_history_choice = apply_to_history is not _APPLY_TO_HISTORY_UNSET
        apply_to_history = False if not explicit_history_choice else apply_to_history
        history_result = {"updated_count": 0}
        if apply_to_history:
            from ..services import rule_history_application_service
            history_result = rule_history_application_service.remove_rule_from_history("folder", rule_id)
        folder_rule_service.delete_folder_rule(rule_id)
        from ..services import context_service
        context_service.invalidate_context_recompute_cache()
        rule = {"kind": "folder", "id": int(rule_id), "deleted": True}
        if explicit_history_choice:
            rule.update({"history_updated": bool(apply_to_history), "updated_count": int(history_result.get("updated_count") or 0)})
        return ok_payload(rule=rule)
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)




def preview_project_rule_impact(rule_type: Any, rule_id: Any) -> dict[str, Any]:
    """Preview the impact of applying one existing folder / keyword rule."""

    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_impact_service

        impact = rule_impact_service.preview_rule_impact(rule_type, rule_id)
        return ok_payload(impact=impact)
    except rule_impact_service.RuleImpactError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def backfill_project_rule(rule_type: Any, rule_id: Any) -> dict[str, Any]:
    """Apply one existing enabled folder / keyword rule to eligible history."""

    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_history_application_service, rule_impact_service

        result = rule_history_application_service.apply_rule_to_history(rule_type, rule_id)
        return ok_payload(result=result)
    except rule_impact_service.RuleImpactError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


# ``file_path_hint`` / ``path_hint`` / clipboard / note / SQL / traceback


def preview_project_rules_batch_impact(rules: Any) -> dict[str, Any]:
    """Read-only aggregate impact preview across the selected rules."""

    if not isinstance(rules, list):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_batch_service

        impact = rule_batch_service.preview_project_rules_batch_impact(rules)
        return ok_payload(impact=impact)
    except rule_batch_service.RuleBatchError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def backfill_project_rules_batch(rules: Any) -> dict[str, Any]:
    """Apply the selected enabled rules to eligible history in one batch."""

    if not isinstance(rules, list):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_batch_service

        result = rule_batch_service.backfill_project_rules_batch(rules)
        return ok_payload(result=result)
    except rule_batch_service.RuleBatchError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def set_project_rules_batch_enabled(rules: Any, enabled: Any) -> dict[str, Any]:
    """Enable or disable every selected rule in one all-or-nothing batch."""

    if not isinstance(rules, list):
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_bool(enabled):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_batch_service

        result = rule_batch_service.set_project_rules_batch_enabled(rules, enabled)
        return ok_payload(result=result)
    except rule_batch_service.RuleBatchError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def automatic_rules_status() -> dict[str, Any]:
    """Return a display-safe status payload for the automatic-rules engine.

    Narrow WebView-facing facade. The Project Rules page uses this to
    render a status note explaining that enabled folder / keyword rules
    are automatically applied to future eligible closed activities. The
    payload is intentionally narrow: it only carries boolean / string
    fields the frontend needs. It never exposes raw rule rows, project
    rows, window titles, file paths, notes, clipboard text, SQL, or
    tracebacks.

    Always succeeds — ``rule_automation_service`` is a thin documented
    facade over the existing inference path and performs no DB access. Any
    unexpected exception collapses to ``operation_failed``.
    """

    try:
        from ..services import rule_automation_service

        status = rule_automation_service.automatic_rules_status()
        return ok_payload(status=status)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)



def create_keyword_rule(keyword: str, project_id: int) -> int:
    return rule_service.create_rule(keyword, project_id)


def set_keyword_rule_enabled(rule_id: int, enabled: bool) -> None:
    rule_service.set_rule_enabled(rule_id, enabled)


def delete_keyword_rule(rule_id: int) -> None:
    rule_service.delete_rule(rule_id)



def create_or_update_folder_rule(folder_path: str, project_id: int, recursive: bool = True) -> int:
    return folder_rule_service.create_or_update_folder_rule(folder_path, project_id, recursive=recursive)


def set_folder_rule_enabled(rule_id: int, enabled: bool) -> None:
    folder_rule_service.set_folder_rule_enabled(rule_id, enabled)


def delete_folder_rule(rule_id: int) -> None:
    folder_rule_service.delete_folder_rule(rule_id)


def preview_folder_rule_conflicts(folder_path: str, project_id: int) -> dict[str, Any]:
    return folder_rule_service.preview_folder_rule_conflicts(folder_path, project_id)




def create_excluded_keyword_rule_for_webview(keyword: Any) -> dict[str, Any]:
    """Create one new keyword rule on the special ``排除规则`` project."""
    trimmed = valid_nonempty_str(keyword)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        excluded_project_id = int(project_service.get_or_create_excluded_project())
        for row in rule_service.list_rules(include_system=True):
            if (
                int(row.get("project_id") or 0) == excluded_project_id
                and str(row.get("keyword") or "") == trimmed
            ):
                return fail_payload(ERROR_DUPLICATE_RULE)
        rule_id = rule_service.create_rule(trimmed, excluded_project_id)
        return ok_payload(
            rule={
                "kind": "keyword",
                "id": int(rule_id),
                "project_id": excluded_project_id,
                "keyword": trimmed,
                "enabled": True,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def create_excluded_folder_rule_for_webview(
    folder_path: Any, recursive: Any
) -> dict[str, Any]:
    """Create one new folder rule on the special ``排除规则`` project."""
    trimmed = valid_nonempty_str(folder_path)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_bool(recursive):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        excluded_project_id = int(project_service.get_or_create_excluded_project())
        rule_id = folder_rule_service.create_or_update_folder_rule(
            trimmed, excluded_project_id, recursive=recursive
        )
        return ok_payload(
            rule={
                "kind": "folder",
                "id": int(rule_id),
                "project_id": excluded_project_id,
                "folder_path": trimmed,
                "recursive": bool(recursive),
                "enabled": True,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


__all__ = [
    "automatic_rules_status",
    "backfill_project_rule",
    "backfill_project_rules_batch",
    "create_excluded_folder_rule_for_webview",
    "create_excluded_keyword_rule_for_webview",
    "create_keyword_rule",
    "create_or_update_folder_rule",
    "create_project_folder_rule",
    "create_project_keyword_rule",
    "delete_folder_rule",
    "delete_keyword_rule",
    "delete_project_folder_rule",
    "delete_project_keyword_rule",
    "ProjectRuleWriteError",
    "preview_folder_rule_conflicts",
    "preview_project_rule_impact",
    "preview_project_rules_batch_impact",
    "set_project_rule_enabled",
    "set_project_rules_batch_enabled",
    "set_folder_rule_enabled",
    "set_keyword_rule_enabled",
    "update_project_folder_rule",
    "update_project_keyword_rule",
]
