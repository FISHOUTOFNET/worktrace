"""Project lifecycle transport facade for the UI.

The facade validates transport values and maps stable domain errors. Project
mutability, reserved identities, archive/delete constraints and name uniqueness
are enforced inside ``project_service`` transactions.
"""
from __future__ import annotations

from typing import Any

from ._write_contract import (
    ERROR_INVALID_INPUT,
    ERROR_OPERATION_FAILED,
    ERROR_SYSTEM_CATALOG_UNAVAILABLE,
    fail_payload,
    ok_payload,
    valid_bool,
    valid_int,
    valid_nonempty_str,
    valid_str,
)
from ..services import project_service
from ..services.project_command_policy import ProjectLifecycleError
from ..services.system_project_service import SystemProjectCatalogUnavailableError


def list_project_bindings() -> list[dict[str, Any]]:
    return project_service.list_project_bindings()


def list_rule_target_projects() -> list[dict[str, Any]]:
    return project_service.list_rule_target_projects()


def list_selectable_projects() -> list[dict[str, Any]]:
    return project_service.list_selectable_projects()


def list_active_projects() -> list[dict[str, Any]]:
    return project_service.list_active_projects()


def list_user_projects() -> list[dict[str, Any]]:
    return project_service.list_user_projects()


def get_project(project_id: int) -> dict[str, Any] | None:
    return project_service.get_project(project_id)


def get_project_by_name(name: str) -> dict[str, Any] | None:
    return project_service.get_project_by_name(name)


def _project_lifecycle_payload(project_id: int) -> dict[str, Any]:
    project = project_service.get_project(project_id)
    if not project:
        return {}
    return {
        "id": int(project.get("id") or 0),
        "name": str(project.get("name") or ""),
        "description": str(project.get("description") or ""),
        "language": str(project.get("language") or "中文"),
        "enabled": bool(int(project.get("enabled") or 0)),
        "archived": bool(int(project.get("is_archived") or 0)),
    }


def _valid_project_language(language: Any) -> str | None:
    if not valid_str(language):
        return None
    return language.strip() or "中文"


def _map_project_error(exc: ProjectLifecycleError) -> dict[str, Any]:
    return fail_payload(exc.code)


def create_project_for_rules(
    name: Any,
    description: Any = "",
    language: Any = "中文",
) -> dict[str, Any]:
    trimmed_name = valid_nonempty_str(name)
    if trimmed_name is None or not valid_str(description):
        return fail_payload(ERROR_INVALID_INPUT)
    cleaned_language = _valid_project_language(language)
    if cleaned_language is None:
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        project_id = project_service.create_project(
            trimmed_name,
            description.strip(),
            cleaned_language,
        )
        payload = _project_lifecycle_payload(project_id)
        return ok_payload(project=payload) if payload else fail_payload(
            ERROR_OPERATION_FAILED
        )
    except ProjectLifecycleError as exc:
        return _map_project_error(exc)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def update_project_for_rules(
    project_id: Any,
    name: Any,
    description: Any = "",
    language: Any = "中文",
) -> dict[str, Any]:
    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed_name = valid_nonempty_str(name)
    if trimmed_name is None or not valid_str(description):
        return fail_payload(ERROR_INVALID_INPUT)
    cleaned_language = _valid_project_language(language)
    if cleaned_language is None:
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        project_service.update_project(
            project_id,
            trimmed_name,
            description.strip(),
            cleaned_language,
        )
        payload = _project_lifecycle_payload(project_id)
        return ok_payload(project=payload) if payload else fail_payload(
            ERROR_OPERATION_FAILED
        )
    except ProjectLifecycleError as exc:
        return _map_project_error(exc)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def set_project_enabled_for_rules(project_id: Any, enabled: Any) -> dict[str, Any]:
    if not valid_int(project_id) or not valid_bool(enabled):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        project_service.set_project_enabled(project_id, enabled)
        payload = _project_lifecycle_payload(project_id)
        return ok_payload(project=payload) if payload else fail_payload(
            ERROR_OPERATION_FAILED
        )
    except ProjectLifecycleError as exc:
        return _map_project_error(exc)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def set_excluded_rules_enabled(enabled: Any) -> dict[str, Any]:
    if not valid_bool(enabled):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        project_id = project_service.set_excluded_project_enabled(enabled)
        payload = _project_lifecycle_payload(project_id)
        return ok_payload(project=payload) if payload else fail_payload(
            ERROR_OPERATION_FAILED
        )
    except SystemProjectCatalogUnavailableError:
        return fail_payload(ERROR_SYSTEM_CATALOG_UNAVAILABLE)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def archive_project_for_rules(project_id: Any) -> dict[str, Any]:
    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        project_service.archive_project(project_id)
        payload = _project_lifecycle_payload(project_id)
        return ok_payload(project=payload) if payload else fail_payload(
            ERROR_OPERATION_FAILED
        )
    except ProjectLifecycleError as exc:
        return _map_project_error(exc)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def delete_project_for_rules(project_id: Any) -> dict[str, Any]:
    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        project_service.soft_delete_project(project_id)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return fail_payload(ERROR_OPERATION_FAILED)
        payload["deleted"] = True
        return ok_payload(project=payload)
    except ProjectLifecycleError as exc:
        return _map_project_error(exc)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


__all__ = [
    "archive_project_for_rules",
    "create_project_for_rules",
    "delete_project_for_rules",
    "get_project",
    "get_project_by_name",
    "list_active_projects",
    "list_project_bindings",
    "list_rule_target_projects",
    "list_selectable_projects",
    "list_user_projects",
    "set_project_enabled_for_rules",
    "set_excluded_rules_enabled",
    "update_project_for_rules",
]
