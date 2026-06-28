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


# --- Phase 5E: Project Rules folder rule CRUD foundation -----------------


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
    """Create one new folder rule on an existing rule-target project.

    Phase 5E narrow WebView-facing facade. ``project_id`` must identify a
    project returned by ``project_api.list_rule_target_projects()`` (the
    same eligibility rule the legacy Tkinter dialog and Phase 5C keyword
    creation use), so the special local ``排除规则`` project — which is
    created with ``enabled = 0`` and is therefore not a rule target — is
    rejected as ``project_not_found`` without bypassing the service. The
    existing ``folder_rule_service.create_or_update_folder_rule`` write path
    uses ``INSERT ... ON CONFLICT(normalized_folder_key) DO UPDATE`` and so
    has create-or-update semantics: if a folder rule with the same
    normalized folder key already exists, it is updated in place (the
    folder_path / project_id / recursive / enabled fields are overwritten
    and ``enabled`` is reset to ``1``). This facade wraps that behavior as
    a stable "create/update single folder rule" contract and returns the
    resulting rule id, so callers cannot distinguish a fresh insert from an
    in-place update at the API boundary.

    It does NOT create projects, keyword rules, or edit/delete existing
    folder rules; it does NOT perform conflict preview, backfill,
    automatic rules, DB schema changes, native file picker dialogs, or
    network access.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``project_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / tuple /
      set / frozenset / zero / negative), or ``folder_path`` is not a real
      non-empty ``str`` after trim, or ``recursive`` is not a real ``bool``.
    - ``project_not_found`` — the project is not a rule target (covers both
      unknown ids and disabled / archived / excluded projects).
    - ``operation_failed`` — any unexpected service failure.
    """

    # ``type(...) is not int`` rejects ``bool`` (since ``type(True) is bool``),
    # ``float``, ``str``, ``None``, and container types in one check.
    if type(project_id) is not int or project_id <= 0:
        return {"ok": False, "error": "invalid_input"}
    if type(folder_path) is not str:
        return {"ok": False, "error": "invalid_input"}
    trimmed = folder_path.strip()
    if not trimmed:
        return {"ok": False, "error": "invalid_input"}
    if type(recursive) is not bool:
        return {"ok": False, "error": "invalid_input"}
    try:
        target_ids = {
            int(row.get("id") or 0)
            for row in project_api.list_rule_target_projects()
        }
        if project_id not in target_ids:
            return {"ok": False, "error": "project_not_found"}
        rule_id = folder_rule_service.create_or_update_folder_rule(
            trimmed, project_id, recursive=recursive
        )
        return {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": int(rule_id),
                "project_id": int(project_id),
                "folder_path": trimmed,
                "recursive": bool(recursive),
                "enabled": True,
            },
        }
    except ProjectRuleWriteError as exc:
        return {"ok": False, "error": exc.code}
    except Exception:
        return {"ok": False, "error": "operation_failed"}


def update_project_folder_rule(
    rule_id: Any, folder_path: Any, recursive: Any
) -> dict[str, Any]:
    """Update one existing folder rule's ``folder_path`` and ``recursive``.

    Phase 5E narrow WebView-facing facade. ``rule_id`` must identify an
    existing row in ``folder_project_rule`` (the folder rule table). A
    ``rule_id`` that points at a keyword rule (``project_rule``) is rejected
    as ``not_found`` rather than modifying the keyword rule — the folder
    update path must never touch keyword rules. The folder rule's
    ``project_id`` is intentionally preserved: this facade does not support
    moving a folder rule to a different project. ``enabled`` is preserved
    as-is (use the existing ``set_project_rule_enabled`` toggle path to
    change enabled state).

    The existing ``folder_rule_service.update_folder_rule`` write path
    performs a direct ``UPDATE`` on the row identified by ``rule_id`` so
    the row id is preserved even when the new ``folder_path`` produces a
    different ``normalized_folder_key``. If the new normalized key already
    belongs to a different folder rule, the service's
    ``UNIQUE`` constraint raises ``IntegrityError`` which this facade
    collapses to ``operation_failed`` — the update path does NOT merge or
    delete the other rule. The folder rule cache invalidation, privacy
    exclude cache clearing, and folder index rebuild hooks fire exactly as
    they do on create.

    It does NOT create projects or keyword rules, edit/delete existing
    rules or projects, or perform conflict preview / backfill / automatic
    rules / DB schema changes / native dialogs / file writes / network
    access.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rule_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / tuple /
      set / frozenset / zero / negative), or ``folder_path`` is not a real
      non-empty ``str`` after trim, or ``recursive`` is not a real ``bool``.
    - ``not_found`` — no folder rule exists with this id (covers both
      "id does not exist at all" and "id is a keyword rule").
    - ``operation_failed`` — any unexpected service failure.
    """

    # ``type(...) is not int`` rejects ``bool`` (since ``type(True) is bool``),
    # ``float``, ``str``, ``None``, and container types in one check.
    if type(rule_id) is not int or rule_id <= 0:
        return {"ok": False, "error": "invalid_input"}
    if type(folder_path) is not str:
        return {"ok": False, "error": "invalid_input"}
    trimmed = folder_path.strip()
    if not trimmed:
        return {"ok": False, "error": "invalid_input"}
    if type(recursive) is not bool:
        return {"ok": False, "error": "invalid_input"}
    try:
        # ``_folder_rule_row`` only resolves ids in ``folder_project_rule``;
        # a keyword rule id resolves to ``None`` and therefore returns
        # ``not_found``, so the folder update path can never modify a
        # keyword rule.
        existing = _folder_rule_row(rule_id)
        if existing is None:
            return {"ok": False, "error": "not_found"}
        # Preserve the existing project_id and enabled state: this facade
        # does not move a folder rule to a different project and does not
        # toggle its enabled state. Delegate to the dedicated
        # ``update_folder_rule`` service write path (which preserves the
        # row id even when the normalized folder key changes) so the cache
        # invalidation / privacy exclude cache clearing / folder index
        # rebuild hooks all fire exactly as they do on create.
        project_id = int(existing.get("project_id") or 0)
        enabled = bool(int(existing.get("enabled") or 0))
        folder_rule_service.update_folder_rule(
            rule_id, trimmed, recursive=recursive
        )
        return {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": int(rule_id),
                "project_id": project_id,
                "folder_path": trimmed,
                "recursive": bool(recursive),
                "enabled": enabled,
            },
        }
    except ProjectRuleWriteError as exc:
        return {"ok": False, "error": exc.code}
    except Exception:
        return {"ok": False, "error": "operation_failed"}


def delete_project_folder_rule(rule_id: Any) -> dict[str, Any]:
    """Delete one existing folder rule.

    Phase 5E narrow WebView-facing facade. It only deletes a folder rule;
    it does not delete keyword rules, projects, or edit/enable/disable any
    rule or project. ``rule_id`` must identify an existing row in
    ``folder_project_rule`` (the folder rule table). A ``rule_id`` that
    points at a keyword rule (``project_rule``) is rejected as
    ``not_found`` rather than deleting the keyword rule — the folder delete
    path must never touch keyword rules. The facade delegates to the
    existing ``folder_rule_service.delete_folder_rule`` write path, which
    performs a hard ``DELETE FROM folder_project_rule`` and preserves the
    existing folder rule cache invalidation, privacy exclude cache
    clearing, and folder index deletion. No soft-delete is invented.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rule_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / tuple /
      set / frozenset / zero / negative).
    - ``not_found`` — no folder rule exists with this id (covers both
      "id does not exist at all" and "id is a keyword rule").
    - ``operation_failed`` — any unexpected service failure.
    """

    # ``type(...) is not int`` rejects ``bool`` (since ``type(True) is bool``),
    # ``float``, ``str``, ``None``, and container types in one check.
    if type(rule_id) is not int or rule_id <= 0:
        return {"ok": False, "error": "invalid_input"}
    try:
        # ``_folder_rule_row`` only resolves ids in ``folder_project_rule``;
        # a keyword rule id resolves to ``None`` and therefore returns
        # ``not_found``, so the folder delete path can never delete a
        # keyword rule.
        if _folder_rule_row(rule_id) is None:
            return {"ok": False, "error": "not_found"}
        folder_rule_service.delete_folder_rule(rule_id)
        return {
            "ok": True,
            "rule": {
                "kind": "folder",
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
    "create_project_folder_rule",
    "create_project_keyword_rule",
    "delete_folder_rule",
    "delete_keyword_rule",
    "delete_project_folder_rule",
    "delete_project_keyword_rule",
    "ProjectRuleWriteError",
    "preview_folder_rule_conflicts",
    "set_project_rule_enabled",
    "set_folder_rule_enabled",
    "set_keyword_rule_enabled",
    "update_project_folder_rule",
]
