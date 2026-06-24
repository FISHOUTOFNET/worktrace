"""Project CRUD facade for the UI.

Wraps ``project_service`` for project listing, creation, update, enable/disable,
archive, and delete operations used by the Project Rules page and dialogs.
"""

from __future__ import annotations

from typing import Any

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


__all__ = [
    "archive_project",
    "create_project",
    "delete_project",
    "get_project",
    "get_project_by_name",
    "list_active_projects",
    "list_project_bindings",
    "list_rule_target_projects",
    "list_selectable_projects",
    "list_user_projects",
    "set_project_enabled",
    "update_project",
]
