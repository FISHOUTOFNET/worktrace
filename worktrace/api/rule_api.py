"""Keyword-rule and folder-rule transport facade for the UI.

The facade validates transport types and maps stable domain errors. Durable
uniqueness, project eligibility and mutation atomicity remain in the canonical
rule catalog command owner.
"""
from __future__ import annotations

from typing import Any

from ._write_contract import (
    ERROR_INVALID_INPUT,
    ERROR_NOT_FOUND,
    ERROR_OPERATION_FAILED,
    fail_payload,
    ok_payload,
    valid_bool,
    valid_int,
    valid_nonempty_str,
)
from ..services import (
    folder_rule_service,
    rule_catalog_command_service,
    rule_history_application_service,
    rule_impact_service,
    rule_query_service,
)
from ..services.keyword_rule_policy import ProjectRuleWriteError

_APPLY_TO_HISTORY_UNSET = object()


def set_project_rule_enabled(
    rule_type: str,
    rule_id: int,
    enabled: bool,
) -> dict[str, Any]:
    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_int(rule_id) or not valid_bool(enabled):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        if rule_type == "folder":
            changed = rule_catalog_command_service.set_folder_rule_enabled(
                rule_id,
                enabled,
            )
        else:
            changed = rule_catalog_command_service.set_keyword_rule_enabled(
                rule_id,
                enabled,
            )
        if not changed:
            return fail_payload(ERROR_NOT_FOUND)
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
    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed = valid_nonempty_str(keyword)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        rule_id = rule_catalog_command_service.create_keyword_rule(trimmed, project_id)
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


def delete_project_keyword_rule(
    rule_id: Any,
    apply_to_history: Any = _APPLY_TO_HISTORY_UNSET,
) -> dict[str, Any]:
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    if (
        apply_to_history is not _APPLY_TO_HISTORY_UNSET
        and not valid_bool(apply_to_history)
    ):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        explicit_history_choice = apply_to_history is not _APPLY_TO_HISTORY_UNSET
        requested_history = False if not explicit_history_choice else apply_to_history
        history_result = rule_history_application_service.delete_rule(
            "keyword",
            rule_id,
            requested_history,
        )
        rule = {"kind": "keyword", "id": int(rule_id), "deleted": True}
        if explicit_history_choice:
            rule.update(
                {
                    "history_updated": bool(requested_history),
                    "updated_count": int(history_result.get("updated_count") or 0),
                }
            )
        return ok_payload(rule=rule)
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except rule_impact_service.RuleImpactError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def update_project_keyword_rule(rule_id: Any, keyword: Any) -> dict[str, Any]:
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed = valid_nonempty_str(keyword)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        existing = rule_query_service.get_keyword_rule(rule_id)
        if existing is None:
            return fail_payload(ERROR_NOT_FOUND)
        if not rule_catalog_command_service.update_keyword_rule(rule_id, trimmed):
            return fail_payload(ERROR_NOT_FOUND)
        return ok_payload(
            rule={
                "kind": "keyword",
                "id": int(rule_id),
                "project_id": int(existing.get("project_id") or 0),
                "keyword": trimmed,
                "enabled": bool(int(existing.get("enabled") or 0)),
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def create_project_folder_rule(
    project_id: Any,
    folder_path: Any,
    recursive: Any,
) -> dict[str, Any]:
    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed = valid_nonempty_str(folder_path)
    if trimmed is None or not valid_bool(recursive):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        rule_id = rule_catalog_command_service.create_or_update_folder_rule(
            trimmed,
            project_id,
            recursive=recursive,
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
    rule_id: Any,
    folder_path: Any,
    recursive: Any,
) -> dict[str, Any]:
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed = valid_nonempty_str(folder_path)
    if trimmed is None or not valid_bool(recursive):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        existing = rule_query_service.get_folder_rule(rule_id)
        if existing is None:
            return fail_payload(ERROR_NOT_FOUND)
        if not rule_catalog_command_service.update_folder_rule(
            rule_id,
            trimmed,
            recursive=recursive,
        ):
            return fail_payload(ERROR_NOT_FOUND)
        return ok_payload(
            rule={
                "kind": "folder",
                "id": int(rule_id),
                "project_id": int(existing.get("project_id") or 0),
                "folder_path": trimmed,
                "recursive": bool(recursive),
                "enabled": bool(int(existing.get("enabled") or 0)),
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def delete_project_folder_rule(
    rule_id: Any,
    apply_to_history: Any = _APPLY_TO_HISTORY_UNSET,
) -> dict[str, Any]:
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    if (
        apply_to_history is not _APPLY_TO_HISTORY_UNSET
        and not valid_bool(apply_to_history)
    ):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        explicit_history_choice = apply_to_history is not _APPLY_TO_HISTORY_UNSET
        requested_history = False if not explicit_history_choice else apply_to_history
        history_result = rule_history_application_service.delete_rule(
            "folder",
            rule_id,
            requested_history,
        )
        rule = {"kind": "folder", "id": int(rule_id), "deleted": True}
        if explicit_history_choice:
            rule.update(
                {
                    "history_updated": bool(requested_history),
                    "updated_count": int(history_result.get("updated_count") or 0),
                }
            )
        return ok_payload(rule=rule)
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except rule_impact_service.RuleImpactError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def preview_folder_rule_conflicts(folder_path: str, project_id: int) -> dict[str, Any]:
    return folder_rule_service.preview_folder_rule_conflicts(folder_path, project_id)


def create_excluded_keyword_rule_for_webview(keyword: Any) -> dict[str, Any]:
    trimmed = valid_nonempty_str(keyword)
    if trimmed is None:
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        rule_id, excluded_project_id = (
            rule_catalog_command_service.create_excluded_keyword_rule(trimmed)
        )
        return ok_payload(
            rule={
                "kind": "keyword",
                "id": int(rule_id),
                "project_id": int(excluded_project_id),
                "keyword": trimmed,
                "enabled": True,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def create_excluded_folder_rule_for_webview(
    folder_path: Any,
    recursive: Any,
) -> dict[str, Any]:
    trimmed = valid_nonempty_str(folder_path)
    if trimmed is None or not valid_bool(recursive):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        rule_id, excluded_project_id = (
            rule_catalog_command_service.create_or_update_excluded_folder_rule(
                trimmed,
                recursive=recursive,
            )
        )
        return ok_payload(
            rule={
                "kind": "folder",
                "id": int(rule_id),
                "project_id": int(excluded_project_id),
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
    "create_excluded_folder_rule_for_webview",
    "create_excluded_keyword_rule_for_webview",
    "create_project_folder_rule",
    "create_project_keyword_rule",
    "delete_project_folder_rule",
    "delete_project_keyword_rule",
    "preview_folder_rule_conflicts",
    "set_project_rule_enabled",
    "update_project_folder_rule",
    "update_project_keyword_rule",
]
