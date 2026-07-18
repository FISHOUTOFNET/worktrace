from __future__ import annotations

from typing import Any

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT

RESERVED_PROJECT_NAMES = frozenset({UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT})


def project_name_is_reserved(name: str | None) -> bool:
    return str(name or "").strip() in RESERVED_PROJECT_NAMES


def project_is_deleted(project: dict[str, Any] | None) -> bool:
    return bool(project and int(project.get("is_deleted") or 0))


def project_is_archived(project: dict[str, Any] | None) -> bool:
    return bool(project and int(project.get("is_archived") or 0))


def project_is_system_or_special(project: dict[str, Any] | None) -> bool:
    if not project:
        return False
    return project.get("created_by") == "system" or project_name_is_reserved(
        project.get("name")
    )


def project_rules_capabilities(project: dict[str, Any] | None) -> dict[str, bool]:
    """Return neutral Project Rules lifecycle capabilities for presentation."""

    is_system = project_is_system_or_special(project)
    is_excluded = bool(project and project.get("name") == EXCLUDED_PROJECT)
    return {
        "is_system": is_system,
        "is_excluded": is_excluded,
        "editable": not is_system,
        "can_toggle": not is_system,
        "can_archive": not is_system,
    }


def project_available_for_rules(project: dict[str, Any] | None) -> bool:
    return bool(
        project
        and not project_is_deleted(project)
        and not project_is_archived(project)
        and int(project.get("enabled") or 0) == 1
        and project.get("created_by") == "user"
        and project.get("name") != EXCLUDED_PROJECT
    )


def project_selectable_for_editing(project: dict[str, Any] | None) -> bool:
    return bool(
        project
        and not project_is_deleted(project)
        and not project_is_archived(project)
        and int(project.get("enabled") or 0) == 1
        and (project.get("created_by") == "user" or project.get("name") == UNCATEGORIZED_PROJECT)
        and project.get("name") != EXCLUDED_PROJECT
    )


def project_available_for_inference(project: dict[str, Any] | None) -> bool:
    return bool(
        project
        and not project_is_deleted(project)
        and not project_is_archived(project)
        and int(project.get("enabled") or 0) == 1
        and project.get("name") != EXCLUDED_PROJECT
    )


def project_visible_in_rules_page(project: dict[str, Any] | None, *, include_system_special: bool) -> bool:
    if not project or project_is_deleted(project) or project_is_archived(project):
        return False
    return project.get("created_by") == "user" or (
        include_system_special and project.get("name") == EXCLUDED_PROJECT
    )


def final_session_is_reportable(session: dict[str, Any]) -> bool:
    """Deleted final project sessions are suppressed after overrides resolve."""
    return not bool(session.get("project_is_deleted"))
