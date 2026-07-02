"""Project CRUD facade for the UI.

Wraps ``project_service`` for project listing, creation, update, enable/disable,
archive, and delete operations used by the Project Rules page and dialogs.

Shared write-path validation / fail / success payloads come from
``worktrace.api._write_contract`` so every Project Rules project-lifecycle
facade uses the same "true positive int", "true bool", "true non-empty str",
and stable ``{"ok": False, "error": code}`` / ``{"ok": True, ...}`` shapes.

This facade owns create/edit/toggle/archive/delete calls, rejects system or
special-project modification, and returns stable error-code payloads without
DB schema changes, native dialogs, or network access.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ._write_contract import (
    ERROR_DUPLICATE_PROJECT,
    ERROR_INVALID_INPUT,
    ERROR_NOT_FOUND,
    ERROR_OPERATION_FAILED,
    ERROR_SYSTEM_PROJECT,
    fail_payload,
    ok_payload,
    valid_bool,
    valid_int,
    valid_nonempty_str,
    valid_str,
)
from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from ..services import project_service


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


def create_project(name: str, description: str = "") -> int:
    return project_service.create_project(name, description)


def update_project(project_id: int, name: str, description: str = "") -> None:
    project_service.update_project(project_id, name, description)


def set_project_enabled(project_id: int, enabled: bool) -> None:
    project_service.set_project_enabled(project_id, enabled)


def archive_project(project_id: int) -> None:
    project_service.archive_project(project_id)


def delete_project(project_id: int) -> None:
    project_service.delete_project(project_id)




def _is_system_or_special_project(project: dict[str, Any]) -> bool:
    """Return True if the project is a system/special project that cannot be modified.

    A project is considered system/special if ``created_by == "system"`` or its
    name matches one of the reserved special project names (``未归类`` /
    ``排除规则``). This helper never leaks the raw ``created_by`` value to the
    caller; it only returns a boolean for the API facade's display-safe
    rejection logic.
    """
    if project.get("created_by") == "system":
        return True
    if project.get("name") in {UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT}:
        return True
    return False


def _project_lifecycle_payload(project_id: int) -> dict[str, Any]:
    """Build the narrow project summary payload for project lifecycle writes.

    Returns an empty dict if the project cannot be loaded so callers can
    treat a missing project as ``operation_failed`` rather than echoing a
    partial payload.
    """
    project = project_service.get_project(project_id)
    if not project:
        return {}
    return {
        "id": int(project.get("id") or 0),
        "name": str(project.get("name") or ""),
        "description": str(project.get("description") or ""),
        "enabled": bool(int(project.get("enabled") or 0)),
        "archived": bool(int(project.get("is_archived") or 0)),
    }


def create_project_for_rules(name: Any, description: Any = "") -> dict[str, Any]:
    """Create one new user project from the Project Rules page."""
    # ``valid_nonempty_str`` returns the trimmed name or ``None`` (rejecting
    # non-strings and empty-after-trim in one helper call). ``valid_str``
    # rejects non-strings so a non-string description never reaches the
    # service; empty description is allowed, so we trim separately.
    trimmed_name = valid_nonempty_str(name)
    if trimmed_name is None:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_str(description):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed_description = description.strip()
    try:
        # Conservative duplicate check: reject if another project already
        # has the same trimmed name. This catches the common case before
        # the INSERT; the IntegrityError catch below handles any race.
        existing = project_service.get_project_by_name(trimmed_name)
        if existing:
            return fail_payload(ERROR_DUPLICATE_PROJECT)
        project_id = project_service.create_project(trimmed_name, trimmed_description)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return fail_payload(ERROR_OPERATION_FAILED)
        return ok_payload(project=payload)
    except sqlite3.IntegrityError:
        return fail_payload(ERROR_DUPLICATE_PROJECT)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def update_project_for_rules(project_id: Any, name: Any, description: Any = "") -> dict[str, Any]:
    """Update one existing user project's name and description."""
    # ``type(...) is not int`` rejects ``bool`` (``type(True) is bool``),
    # ``float``, ``str``, ``None``, and container types in one check.
    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed_name = valid_nonempty_str(name)
    if trimmed_name is None:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_str(description):
        return fail_payload(ERROR_INVALID_INPUT)
    trimmed_description = description.strip()
    try:
        project = project_service.get_project(project_id)
        if not project:
            return fail_payload(ERROR_NOT_FOUND)
        if _is_system_or_special_project(project):
            return fail_payload(ERROR_SYSTEM_PROJECT)
        # Duplicate check: reject if a DIFFERENT project already has the
        # same trimmed name. Updating a project to its own current name
        # is allowed. IntegrityError catch below handles any race.
        existing = project_service.get_project_by_name(trimmed_name)
        if existing and int(existing.get("id") or 0) != project_id:
            return fail_payload(ERROR_DUPLICATE_PROJECT)
        project_service.update_project(project_id, trimmed_name, trimmed_description)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return fail_payload(ERROR_OPERATION_FAILED)
        return ok_payload(project=payload)
    except sqlite3.IntegrityError:
        return fail_payload(ERROR_DUPLICATE_PROJECT)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def set_project_enabled_for_rules(project_id: Any, enabled: Any) -> dict[str, Any]:
    """Enable or disable one existing user project."""
    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_bool(enabled):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        project = project_service.get_project(project_id)
        if not project:
            return fail_payload(ERROR_NOT_FOUND)
        if _is_system_or_special_project(project):
            return fail_payload(ERROR_SYSTEM_PROJECT)
        project_service.set_project_enabled(project_id, enabled)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return fail_payload(ERROR_OPERATION_FAILED)
        return ok_payload(project=payload)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def archive_project_for_rules(project_id: Any) -> dict[str, Any]:
    """Archive one existing user project."""
    if not valid_int(project_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        project = project_service.get_project(project_id)
        if not project:
            return fail_payload(ERROR_NOT_FOUND)
        if _is_system_or_special_project(project):
            return fail_payload(ERROR_SYSTEM_PROJECT)
        project_service.archive_project(project_id)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return fail_payload(ERROR_OPERATION_FAILED)
        return ok_payload(project=payload)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


__all__ = [
    "archive_project",
    "archive_project_for_rules",
    "create_project",
    "create_project_for_rules",
    "delete_project",
    "get_project",
    "get_project_by_name",
    "list_active_projects",
    "list_project_bindings",
    "list_rule_target_projects",
    "list_selectable_projects",
    "list_user_projects",
    "set_project_enabled",
    "set_project_enabled_for_rules",
    "update_project",
    "update_project_for_rules",
]
