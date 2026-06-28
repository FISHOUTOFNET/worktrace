"""Project CRUD facade for the UI.

Wraps ``project_service`` for project listing, creation, update, enable/disable,
archive, and delete operations used by the Project Rules page and dialogs.
"""

from __future__ import annotations

import sqlite3
from typing import Any

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


# --- Phase 5G: Project lifecycle foundation (create / edit / toggle / archive) ---


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
    """Create one new user project from the Project Rules page.

    Phase 5G narrow WebView-facing facade. It only creates a user project;
    it does NOT create folder/keyword rules, edit/delete existing projects,
    or perform conflict preview / backfill / automatic rules / DB schema
    changes / native dialogs / file writes / network access.

    ``name`` must be a real non-empty ``str`` after trim. ``description``
    must be a real ``str`` (empty allowed) and is trimmed before save. An
    exact duplicate project name (trim-compared) is rejected as
    ``duplicate_project``; a SQLite ``IntegrityError`` from the underlying
    ``UNIQUE(name)`` constraint is also collapsed to ``duplicate_project``
    so a race cannot leak a raw SQL error.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``name`` is not a real non-empty ``str`` after
      trim, or ``description`` is not a real ``str``.
    - ``duplicate_project`` — another project already has the same trimmed
      name.
    - ``operation_failed`` — any unexpected service failure.
    """
    # ``type(...) is not str`` rejects ``bool`` / ``int`` / ``float`` /
    # ``None`` / container types so a non-string name never reaches the
    # service. ``description`` must also be a real ``str`` (empty allowed).
    if type(name) is not str:
        return {"ok": False, "error": "invalid_input"}
    if type(description) is not str:
        return {"ok": False, "error": "invalid_input"}
    trimmed_name = name.strip()
    if not trimmed_name:
        return {"ok": False, "error": "invalid_input"}
    trimmed_description = description.strip()
    try:
        # Conservative duplicate check: reject if another project already
        # has the same trimmed name. This catches the common case before
        # the INSERT; the IntegrityError catch below handles any race.
        existing = project_service.get_project_by_name(trimmed_name)
        if existing:
            return {"ok": False, "error": "duplicate_project"}
        project_id = project_service.create_project(trimmed_name, trimmed_description)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return {"ok": False, "error": "operation_failed"}
        return {"ok": True, "project": payload}
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "duplicate_project"}
    except Exception:
        return {"ok": False, "error": "operation_failed"}


def update_project_for_rules(project_id: Any, name: Any, description: Any = "") -> dict[str, Any]:
    """Update one existing user project's name and description.

    Phase 5G narrow WebView-facing facade. It only edits a user project's
    name/description; it does NOT touch ``enabled`` / ``is_archived`` /
    ``created_by`` / ``created_at``, create/delete projects, or perform
    conflict preview / backfill / automatic rules / DB schema changes /
    native dialogs / file writes / network access.

    ``project_id`` must be a real positive ``int`` (bool rejected).
    ``name`` must be a real non-empty ``str`` after trim. ``description``
    must be a real ``str`` (empty allowed) and is trimmed before save.
    System/special projects (``created_by == "system"``, ``未归类``,
    ``排除规则``) are rejected as ``system_project``. An exact duplicate
    project name (trim-compared, excluding the project being edited) is
    rejected as ``duplicate_project``; a SQLite ``IntegrityError`` from the
    underlying ``UNIQUE(name)`` constraint is also collapsed to
    ``duplicate_project``.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``project_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / zero /
      negative), ``name`` is not a real non-empty ``str`` after trim, or
      ``description`` is not a real ``str``.
    - ``not_found`` — no project exists with this id.
    - ``system_project`` — the project is a system/special project.
    - ``duplicate_project`` — another project already has the same trimmed
      name.
    - ``operation_failed`` — any unexpected service failure.
    """
    # ``type(...) is not int`` rejects ``bool`` (``type(True) is bool``),
    # ``float``, ``str``, ``None``, and container types in one check.
    if type(project_id) is not int or project_id <= 0:
        return {"ok": False, "error": "invalid_input"}
    if type(name) is not str:
        return {"ok": False, "error": "invalid_input"}
    if type(description) is not str:
        return {"ok": False, "error": "invalid_input"}
    trimmed_name = name.strip()
    if not trimmed_name:
        return {"ok": False, "error": "invalid_input"}
    trimmed_description = description.strip()
    try:
        project = project_service.get_project(project_id)
        if not project:
            return {"ok": False, "error": "not_found"}
        if _is_system_or_special_project(project):
            return {"ok": False, "error": "system_project"}
        # Duplicate check: reject if a DIFFERENT project already has the
        # same trimmed name. Updating a project to its own current name
        # is allowed. IntegrityError catch below handles any race.
        existing = project_service.get_project_by_name(trimmed_name)
        if existing and int(existing.get("id") or 0) != project_id:
            return {"ok": False, "error": "duplicate_project"}
        project_service.update_project(project_id, trimmed_name, trimmed_description)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return {"ok": False, "error": "operation_failed"}
        return {"ok": True, "project": payload}
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "duplicate_project"}
    except Exception:
        return {"ok": False, "error": "operation_failed"}


def set_project_enabled_for_rules(project_id: Any, enabled: Any) -> dict[str, Any]:
    """Enable or disable one existing user project.

    Phase 5G narrow WebView-facing facade. It only toggles a user project's
    ``enabled`` flag; it does NOT touch ``name`` / ``description`` /
    ``is_archived`` / ``created_by`` / ``created_at``, create/delete/edit
    projects, or perform conflict preview / backfill / automatic rules /
    DB schema changes / native dialogs / file writes / network access.

    ``project_id`` must be a real positive ``int`` (bool rejected).
    ``enabled`` must be a real ``bool``. System/special projects
    (``created_by == "system"``, ``未归类``, ``排除规则``) are rejected as
    ``system_project`` — in particular, ``排除规则`` must never be enabled
    via this path.

    The existing ``project_service.set_project_enabled`` already triggers
    the folder rule cache, keyword rule cache, and privacy exclude cache
    invalidation hooks on success; this facade does not add or remove any
    cache invalidation. Rejections (invalid / not_found / system) do not
    trigger the cache hooks.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``project_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / zero /
      negative), or ``enabled`` is not a real ``bool``.
    - ``not_found`` — no project exists with this id.
    - ``system_project`` — the project is a system/special project.
    - ``operation_failed`` — any unexpected service failure.
    """
    if type(project_id) is not int or project_id <= 0:
        return {"ok": False, "error": "invalid_input"}
    if type(enabled) is not bool:
        return {"ok": False, "error": "invalid_input"}
    try:
        project = project_service.get_project(project_id)
        if not project:
            return {"ok": False, "error": "not_found"}
        if _is_system_or_special_project(project):
            return {"ok": False, "error": "system_project"}
        project_service.set_project_enabled(project_id, enabled)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return {"ok": False, "error": "operation_failed"}
        return {"ok": True, "project": payload}
    except Exception:
        return {"ok": False, "error": "operation_failed"}


def archive_project_for_rules(project_id: Any) -> dict[str, Any]:
    """Archive one existing user project.

    Phase 5G narrow WebView-facing facade. It only sets ``is_archived = 1``
    on a user project; it does NOT physically delete the project, its
    folder rules, its keyword rules, or any activity rows. It does NOT
    touch ``name`` / ``description`` / ``enabled`` / ``created_by`` /
    ``created_at``, create/delete/edit projects, or perform conflict
    preview / backfill / automatic rules / DB schema changes / native
    dialogs / file writes / network access.

    ``project_id`` must be a real positive ``int`` (bool rejected).
    System/special projects (``created_by == "system"``, ``未归类``,
    ``排除规则``) are rejected as ``system_project``.

    The existing ``project_service.archive_project`` triggers the folder
    rule cache, keyword rule cache, and privacy exclude cache invalidation
    hooks on success (added in Phase 5G) because archiving a project
    removes it from the rule target list and so invalidates the cached
    rule target / inference / exclude state. Rejections (invalid /
    not_found / system) do not trigger the cache hooks.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``project_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / zero /
      negative).
    - ``not_found`` — no project exists with this id.
    - ``system_project`` — the project is a system/special project.
    - ``operation_failed`` — any unexpected service failure.
    """
    if type(project_id) is not int or project_id <= 0:
        return {"ok": False, "error": "invalid_input"}
    try:
        project = project_service.get_project(project_id)
        if not project:
            return {"ok": False, "error": "not_found"}
        if _is_system_or_special_project(project):
            return {"ok": False, "error": "system_project"}
        project_service.archive_project(project_id)
        payload = _project_lifecycle_payload(project_id)
        if not payload:
            return {"ok": False, "error": "operation_failed"}
        return {"ok": True, "project": payload}
    except Exception:
        return {"ok": False, "error": "operation_failed"}


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
