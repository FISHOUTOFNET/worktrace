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
    """Create one new keyword rule on an existing rule-target project.

    Narrow WebView-facing facade. Only creates a keyword rule; does not
    create folder rules, projects, or edit/delete existing rules.
    ``project_id`` must identify a project returned by
    ``project_api.list_rule_target_projects()``, so the special local
    ``排除规则`` project — which is created with ``enabled = 0`` and is
    therefore not a rule target — is rejected as ``project_not_found``
    without bypassing the service. The keyword is trimmed before creation
    and an exact duplicate (same ``project_id`` + same trimmed keyword) is
    rejected as ``duplicate_rule``.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``project_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / zero /
      negative) or ``keyword`` is not a real non-empty ``str`` after trim.
    - ``project_not_found`` — the project is not a rule target.
    - ``duplicate_rule`` — an existing keyword rule already binds the same
      keyword to the same project.
    - ``operation_failed`` — any unexpected service failure.
    """

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


def delete_project_keyword_rule(rule_id: Any) -> dict[str, Any]:
    """Delete one existing keyword rule.

    Narrow WebView-facing facade. Only deletes a keyword rule; does not
    delete folder rules, projects, or edit/enable/disable any rule or
    project. ``rule_id`` must identify an existing row in ``project_rule``
    (the keyword rule table). A ``rule_id`` that points at a folder rule
    (``folder_project_rule``) is rejected as ``not_found`` rather than
    deleting the folder rule — the keyword delete path must never touch
    folder rules. The facade delegates to ``rule_service.delete_rule``,
    which performs a hard ``DELETE FROM project_rule`` and preserves the
    existing keyword rule cache invalidation and privacy exclude cache
    clearing.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rule_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / tuple /
      set / frozenset / zero / negative).
    - ``not_found`` — no keyword rule exists with this id (covers both
      "id does not exist at all" and "id is a folder rule").
    - ``operation_failed`` — any unexpected service failure.
    """

    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        # Reuse the existing existence helper: it only returns True when the
        # id resolves to a row in ``project_rule`` (keyword table). A folder
        # rule id resolves to ``folder_project_rule`` and therefore returns
        # False, so the keyword delete path can never delete a folder rule.
        if not _rule_exists("keyword", rule_id):
            return fail_payload(ERROR_NOT_FOUND)
        rule_service.delete_rule(rule_id)
        return ok_payload(
            rule={
                "kind": "keyword",
                "id": int(rule_id),
                "deleted": True,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


# --- Project Rules keyword rule edit foundation ----------------


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
    """Update one existing keyword rule's ``keyword`` text.

    Narrow WebView-facing facade. ``rule_id`` must identify an existing
    row in ``project_rule`` (the keyword rule table). A ``rule_id`` that
    points at a folder rule (``folder_project_rule``) is rejected as
    ``not_found`` rather than modifying the folder rule — the keyword edit
    path must never touch folder rules. The keyword rule's ``project_id``
    is intentionally preserved: this facade does not support moving a
    keyword rule to a different project. ``enabled`` is preserved as-is
    (use the existing ``set_project_rule_enabled`` toggle path to change
    enabled state). ``created_by`` and ``created_at`` are preserved as-is.

    ``rule_service.update_rule`` performs a direct ``UPDATE`` on the row
    identified by ``rule_id`` (guarded by ``rule_type = 'keyword'``),
    updating only ``pattern`` and ``updated_at``. The keyword rule cache
    invalidation and privacy exclude cache clearing hooks fire exactly as
    they do on create.

    An exact duplicate (same ``project_id`` + same trimmed keyword) bound to
    a different keyword rule in the same project is rejected as
    ``duplicate_rule``. Updating a rule to its own current trimmed keyword
    is allowed and succeeds. Different projects may share the same keyword.

    Does NOT create projects or folder rules, edit/delete existing rules or
    projects, or perform conflict preview / backfill / automatic rules /
    DB schema changes / native dialogs / file writes / network access.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rule_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / tuple /
      set / frozenset / zero / negative), or ``keyword`` is not a real
      non-empty ``str`` after trim.
    - ``not_found`` — no keyword rule exists with this id (covers both
      "id does not exist at all" and "id is a folder rule").
    - ``duplicate_rule`` — another keyword rule in the same project already
      binds the same trimmed keyword.
    - ``operation_failed`` — any unexpected service failure.
    """

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


# --- Project Rules folder rule CRUD foundation -----------------


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

    Narrow WebView-facing facade. ``project_id`` must identify a project
    returned by ``project_api.list_rule_target_projects()``, so the special
    local ``排除规则`` project — which is created with ``enabled = 0`` and
    is therefore not a rule target — is rejected as ``project_not_found``
    without bypassing the service. ``folder_rule_service.create_or_update_folder_rule``
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

    Does NOT create projects, keyword rules, or edit/delete existing folder
    rules; does NOT perform conflict preview, backfill, automatic rules,
    DB schema changes, native file picker dialogs, or network access.
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
    """Update one existing folder rule's ``folder_path`` and ``recursive``.

    Narrow WebView-facing facade. ``rule_id`` must identify an existing
    row in ``folder_project_rule`` (the folder rule table). A ``rule_id``
    that points at a keyword rule (``project_rule``) is rejected as
    ``not_found`` rather than modifying the keyword rule — the folder
    update path must never touch keyword rules. The folder rule's
    ``project_id`` is intentionally preserved: this facade does not support
    moving a folder rule to a different project. ``enabled`` is preserved
    as-is (use the existing ``set_project_rule_enabled`` toggle path to
    change enabled state).

    ``folder_rule_service.update_folder_rule`` performs a direct ``UPDATE``
    on the row identified by ``rule_id`` so the row id is preserved even
    when the new ``folder_path`` produces a different
    ``normalized_folder_key``. If the new normalized key already belongs
    to a different folder rule, the service's ``UNIQUE`` constraint raises
    ``IntegrityError`` which this facade collapses to ``operation_failed``
    — the update path does NOT merge or delete the other rule. The folder
    rule cache invalidation, privacy exclude cache clearing, and folder
    index rebuild hooks fire exactly as they do on create.
    they do on create.

    Does NOT create projects or keyword rules, edit/delete existing rules
    or projects, or perform conflict preview / backfill / automatic rules /
    DB schema changes / native dialogs / file writes / network access.
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


def delete_project_folder_rule(rule_id: Any) -> dict[str, Any]:
    """Delete one existing folder rule.

    Narrow WebView-facing facade. Only deletes a folder rule; does not
    delete keyword rules, projects, or edit/enable/disable any rule or
    project. ``rule_id`` must identify an existing row in
    ``folder_project_rule`` (the folder rule table). A ``rule_id`` that
    points at a keyword rule (``project_rule``) is rejected as
    ``not_found`` rather than deleting the keyword rule — the folder delete
    path must never touch keyword rules. The facade delegates to
    ``folder_rule_service.delete_folder_rule``, which performs a hard
    ``DELETE FROM folder_project_rule`` and preserves the existing folder
    rule cache invalidation, privacy exclude cache clearing, and folder
    index deletion.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rule_id`` is not a real positive ``int``
      (bool / float / numeric string / ``None`` / list / dict / tuple /
      set / frozenset / zero / negative).
    - ``not_found`` — no folder rule exists with this id (covers both
      "id does not exist at all" and "id is a keyword rule").
    - ``operation_failed`` — any unexpected service failure.
    """

    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        # ``_folder_rule_row`` only resolves ids in ``folder_project_rule``;
        # a keyword rule id resolves to ``None`` and therefore returns
        # ``not_found``, so the folder delete path can never delete a
        # keyword rule.
        if _folder_rule_row(rule_id) is None:
            return fail_payload(ERROR_NOT_FOUND)
        folder_rule_service.delete_folder_rule(rule_id)
        return ok_payload(
            rule={
                "kind": "folder",
                "id": int(rule_id),
                "deleted": True,
            }
        )
    except ProjectRuleWriteError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


# --- Rule impact preview + safe single-rule backfill ----------


def preview_project_rule_impact(rule_type: Any, rule_id: Any) -> dict[str, Any]:
    """Preview the impact of applying one existing folder / keyword rule.

    Narrow WebView-facing facade. ``rule_type`` must be a real ``str`` in
    ``{"folder", "keyword"}``; ``rule_id`` must be a real positive ``int``
    (bool / float / numeric string / ``None`` / container / zero / negative
    rejected as ``invalid_input``). A folder id resolved on the keyword path
    (or vice versa) is ``not_found`` — the keyword path only resolves ids in
    ``project_rule`` and the folder path only resolves ids in
    ``folder_project_rule``, so the two paths can never touch each other's
    rules.

    Delegates the read-only preview to
    ``rule_impact_service.preview_rule_impact`` and wraps its result in the
    stable ``ok_payload(impact=...)`` envelope. Disabled rules and
    unavailable target projects return ``ok`` with zero counts and empty
    samples (availability is surfaced in the rule summary). Only ``not_found``
    and unexpected service failures produce a fail payload.

    Does NOT write anything, does NOT perform backfill / automatic rules /
    batch operations / DB schema changes, and does NOT expose
    ``window_title`` / ``file_path_hint`` / ``path_hint`` / clipboard / note /
    SQL / traceback / raw activity rows in the payload.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rule_type`` is not ``"folder"`` / ``"keyword"``
      or ``rule_id`` is not a real positive ``int``.
    - ``not_found`` — no folder/keyword rule exists with this id (covers both
      "id does not exist at all" and "id belongs to the other rule table").
    - ``operation_failed`` — any unexpected service failure.
    """

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
    """Apply one existing enabled folder / keyword rule to eligible history.

    Narrow WebView-facing facade. ``rule_type`` must be a real ``str`` in
    ``{"folder", "keyword"}``; ``rule_id`` must be a real positive ``int``
    (bool / float / numeric string / ``None`` / container / zero / negative
    rejected as ``invalid_input``). A folder id resolved on the keyword path
    (or vice versa) is ``not_found``.

    Delegates to ``rule_impact_service.backfill_rule_impact``, which only
    affects eligible existing activities (not deleted / hidden / in-progress
    / non-normal / manual_override / is_manual), never sets
    ``manual_override = 1``, writes ``auto_classified = 1`` and upserts the
    assignment with ``is_manual = 0``, ``source = "folder_rule" |
    "keyword_rule"``, and the inference confidence (85 folder / 80 keyword).
    A single call is capped at ``MAX_RULE_BACKFILL_ACTIVITIES`` (100) updates;
    exceeding the cap returns ``too_many_matches`` and writes nothing. The
    write runs in one transaction with a rowcount guard so any partial write
    is rolled back.

    Does NOT perform automatic rules / batch Project Rules operations /
    hard delete project / project restore / DB schema changes, does NOT
    modify Timeline / Statistics / Export / collector / privacy / encrypted
    backup behavior, and does NOT expose ``window_title`` / ``file_path_hint``
    / ``path_hint`` / clipboard / note / SQL / traceback / raw activity rows
    in the payload.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rule_type`` is not ``"folder"`` / ``"keyword"``
      or ``rule_id`` is not a real positive ``int``.
    - ``not_found`` — no folder/keyword rule exists with this id.
    - ``rule_disabled`` — the rule is disabled; backfill refuses to write.
    - ``project_not_available`` — the rule's target project is disabled /
      archived / the special ``排除规则`` project; backfill refuses to write.
    - ``too_many_matches`` — matched eligible activities exceed the per-call
      cap; nothing is written.
    - ``operation_failed`` — any unexpected service failure (including a
      rowcount-guard rollback).
    """

    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_impact_service

        result = rule_impact_service.backfill_rule_impact(rule_type, rule_id)
        return ok_payload(result=result)
    except rule_impact_service.RuleImpactError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


# --- Selected-rule batch operations + automatic rules ---------
#
# These facades wrap ``rule_batch_service`` (batch preview / batch apply /
# batch enable-disable) and ``rule_automation_service`` (automatic rules
# status). They follow the same stable-code contract as the single-rule
# facades: ``invalid_input`` / ``not_found`` / ``rule_disabled`` /
# ``project_not_available`` / ``too_many_matches`` / ``too_many_rules`` /
# ``operation_failed`` are the only error codes; any unexpected exception
# collapses to ``operation_failed``. The success payload is always a
# narrow, display-safe projection — no raw ``window_title`` /
# ``file_path_hint`` / ``path_hint`` / clipboard / note / SQL / traceback
# / raw activity row is ever returned.
#
# ``rules`` must be a non-empty ``list[dict]`` of
# ``{"rule_type": "folder" | "keyword", "rule_id": positive int}`` items.
# bool-as-int ids, non-int ids, non-positive ids, unknown rule types, and
# non-dict items are ``invalid_input``. After de-duplication (first
# occurrence wins) the rule count must not exceed ``MAX_BATCH_PROJECT_RULES``
# (20) -> ``too_many_rules``. A folder id resolved on the keyword path (or
# vice versa) is ``not_found`` — the two resolver paths can never touch
# each other's rule tables.


def preview_project_rules_batch_impact(rules: Any) -> dict[str, Any]:
    """Read-only aggregate impact preview across the selected rules.

    Narrow WebView-facing facade. ``rules`` must be a non-empty list of
    ``{"rule_type": "folder" | "keyword", "rule_id": positive int}`` dicts.
    Returns aggregate counts + per-rule summaries + up to
    ``MAX_BATCH_SAMPLE_ROWS`` (20) display-safe sample rows across the
    whole batch. Does NOT write anything. Disabled rules and unavailable
    target projects return zero counts for that rule (availability is
    surfaced in the per-rule summary).

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``rules`` is not a non-empty list, an item is not
      a dict, an item is missing required keys, ``rule_type`` is not
      ``"folder"`` / ``"keyword"``, or ``rule_id`` is not a real positive
      ``int``.
    - ``too_many_rules`` — after de-duplication the rule count exceeds 20.
    - ``not_found`` — any rule id does not exist (or a folder id is sent
      on the keyword path / vice versa).
    - ``operation_failed`` — any unexpected service failure.
    """

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
    """Apply the selected enabled rules to eligible history in one batch.

    Narrow WebView-facing facade. ``rules`` must be a non-empty list of
    ``{"rule_type": "folder" | "keyword", "rule_id": positive int}`` dicts.
    Delegates to ``rule_batch_service.backfill_project_rules_batch``, which:
    ``rule_batch_service.backfill_project_rules_batch``, which:

    - runs a full preflight (existence / enabled / project available) on
      every rule before opening the write transaction;
    - rejects disabled rules (``rule_disabled``) and unavailable target
      projects (``project_not_available`` — disabled / archived / excluded)
      as a preflight failure, writing nothing;
    - enforces a total cap of ``MAX_BATCH_BACKFILL_ACTIVITIES`` (100)
      updates across the whole batch; exceeding the cap returns
      ``too_many_matches`` and writes nothing;
    - processes rules in selection order with first-rule-wins: an activity
      updated by an earlier rule is skipped (counted as
      ``collision_skipped``) by later rules;
    - runs in a single transaction with a per-row rowcount guard
      (``manual_override = 0``) so any partial write is rolled back;
    - never sets ``manual_override = 1`` and never touches
      ``assignment.is_manual = 1`` activities, hidden / deleted /
      in-progress / non-normal activities, or activities already on the
      rule's target project;
    - writes ``auto_classified = 1`` and upserts the assignment with
      ``is_manual = 0``, ``source = "folder_rule" | "keyword_rule"``, and
      the inference confidence (85 folder / 80 keyword).

    The success payload only carries aggregate counts + per-rule summaries;
    no raw activity rows are returned.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` / ``too_many_rules`` / ``not_found`` — same as
      ``preview_project_rules_batch_impact``.
    - ``rule_disabled`` — at least one selected rule is disabled.
    - ``project_not_available`` — at least one rule's target project is
      disabled / archived / excluded.
    - ``too_many_matches`` — total eligible activities exceed the batch
      cap; nothing is written.
    - ``operation_failed`` — any unexpected service failure (including a
      rowcount-guard rollback).
    """

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
    """Enable or disable every selected rule in one all-or-nothing batch.

    Narrow WebView-facing facade. ``rules`` must be a non-empty list of
    ``{"rule_type": "folder" | "keyword", "rule_id": positive int}`` dicts.
    ``enabled`` must be a real ``bool`` (``0`` / ``1`` / numeric string /
    ``None`` rejected as ``invalid_input``). Delegates to
    ``rule_batch_service.set_project_rules_batch_enabled``, which:

    - preflights every rule's existence (any missing -> ``not_found``,
      no writes);
    - runs the UPDATEs in one transaction with a per-rule rowcount guard
      so a partial write is rolled back;
    - does NOT call delete / create / edit / backfill;
    - does NOT change any project's enabled state;
    - after commit, fires the existing keyword rule cache / privacy
      exclude cache / folder rule cache invalidation hooks (folder index
      rebuild is intentionally NOT triggered, matching the single-rule
      toggle behavior — enable/disable does not change the folder path /
      key).

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — same as the other batch facades, or ``enabled``
      is not a real ``bool``.
    - ``too_many_rules`` — after de-duplication the rule count exceeds 20.
    - ``not_found`` — any rule id does not exist (or a folder id is sent
      on the keyword path / vice versa).
    - ``operation_failed`` — any unexpected service failure (including a
      rowcount-guard rollback).
    """

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


# --- Excluded-rule creation facades ----------------------------


def create_excluded_keyword_rule_for_webview(keyword: Any) -> dict[str, Any]:
    """Create one new keyword rule on the special ``排除规则`` project.

    Narrow WebView-facing facade. The normal
    ``create_project_keyword_rule`` facade rejects the ``排除规则``
    project because it is created with ``enabled = 0`` and is therefore
    not a rule target. This dedicated facade provides the only legitimate
    way to create an exclusion keyword rule: it internally resolves the
    ``EXCLUDED_PROJECT`` project_id via ``get_or_create_excluded_project``
    and does NOT accept any ``project_id`` from the caller, so the
    frontend cannot inject an arbitrary project_id.

    The keyword is trimmed before creation and an exact duplicate (same
    excluded ``project_id`` + same trimmed keyword) is rejected as
    ``duplicate_rule``.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``keyword`` is not a real non-empty ``str``
      after trim.
    - ``duplicate_rule`` — an existing keyword rule already binds the same
      keyword to the excluded project.
    - ``operation_failed`` — any unexpected service failure.
    """
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
    """Create one new folder rule on the special ``排除规则`` project.

    Narrow WebView-facing facade. The normal
    ``create_project_folder_rule`` facade rejects the ``排除规则``
    project because it is created with ``enabled = 0`` and is therefore
    not a rule target. This dedicated facade provides the only legitimate
    way to create an exclusion folder rule: it internally resolves the
    ``EXCLUDED_PROJECT`` project_id via ``get_or_create_excluded_project``
    and does NOT accept any ``project_id`` from the caller, so the
    frontend cannot inject an arbitrary project_id.

    ``folder_rule_service.create_or_update_folder_rule`` uses
    ``INSERT ... ON CONFLICT(normalized_folder_key) DO UPDATE`` and so has
    create-or-update semantics: if a folder rule with the same normalized
    folder key already exists, it is updated in place.

    Returned errors are stable codes for the bridge to map to Chinese text:

    - ``invalid_input`` — ``folder_path`` is not a real non-empty ``str``
      after trim, or ``recursive`` is not a real ``bool``.
    - ``operation_failed`` — any unexpected service failure.
    """
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
