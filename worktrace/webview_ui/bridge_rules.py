"""Project Rules bridge mixin, payload helpers, and Chinese error-message maps.

Phase M3 split this out of ``bridge.py`` so the Project Rules write/read
surface has its own module. The boundary rules from ``bridge.py`` carry
over verbatim:

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  style payloads without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.

``WebViewBridge`` in ``bridge.py`` inherits ``ProjectRulesBridgeMixin`` so
the 12 Project Rules bridge method names stay on ``WebViewBridge`` and the
frontend / tests see no API-surface change. The module-level payload
helpers (``_project_rules_project_payload`` etc.) and the Chinese
error-message maps (``_PROJECT_RULE_WRITE_MESSAGES`` etc.) live here now;
``bridge.py`` re-exports the names that existing tests reference via
``bridge_module._PROJECT_RULE_...`` for backward compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import project_api, rule_api
from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chinese error-message maps.
# ---------------------------------------------------------------------------
# Each map translates a stable API error code into a user-facing Chinese
# message. Unknown codes collapse to the operation-specific generic failure
# so internal details are never surfaced.

# Maps Project Rules write API stable codes to Phase 5B user-facing messages.
# Unknown codes collapse to the generic update failure.
_PROJECT_RULE_WRITE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "规则不存在",
    "operation_failed": "更新规则状态失败",
}

# Maps Project Rules keyword-create API stable codes to Phase 5C user-facing
# messages. Unknown codes collapse to the generic create failure so internal
# details are never surfaced.
_PROJECT_RULE_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "project_not_found": "项目不存在",
    "duplicate_rule": "关键词规则已存在",
    "operation_failed": "新增关键词规则失败",
}

# Maps Project Rules keyword-delete API stable codes to Phase 5D user-facing
# messages. Unknown codes collapse to the generic delete failure so internal
# details are never surfaced. ``not_found`` covers both "id does not exist"
# and "id is a folder rule" — both are reported as ``关键词规则不存在`` so the
# user never learns which table the id belonged to.
_PROJECT_RULE_DELETE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "关键词规则不存在",
    "operation_failed": "删除关键词规则失败",
}

# Maps Project Rules keyword-update API stable codes to Phase 5F user-facing
# messages. Unknown codes collapse to the generic update failure so internal
# details are never surfaced. ``not_found`` covers both "id does not exist"
# and "id is a folder rule" — both are reported as ``关键词规则不存在`` so the
# user never learns which table the id belonged to.
_PROJECT_RULE_UPDATE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "关键词规则不存在",
    "duplicate_rule": "关键词规则已存在",
    "operation_failed": "保存关键词规则失败",
}

# Maps Project Rules folder-create API stable codes to Phase 5E user-facing
# messages. Unknown codes collapse to the generic create failure so internal
# details are never surfaced.
_PROJECT_RULE_FOLDER_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "project_not_found": "项目不存在或不可用",
    "operation_failed": "新增文件夹规则失败",
}

# Maps Project Rules folder-update API stable codes to Phase 5E user-facing
# messages. Unknown codes collapse to the generic update failure so internal
# details are never surfaced. ``not_found`` covers both "id does not exist"
# and "id is a keyword rule" — both are reported as ``文件夹规则不存在`` so the
# user never learns which table the id belonged to.
_PROJECT_RULE_FOLDER_UPDATE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "文件夹规则不存在",
    "operation_failed": "保存文件夹规则失败",
}

# Maps Project Rules folder-delete API stable codes to Phase 5E user-facing
# messages. Unknown codes collapse to the generic delete failure so internal
# details are never surfaced. ``not_found`` covers both "id does not exist"
# and "id is a keyword rule" — both are reported as ``文件夹规则不存在`` so the
# user never learns which table the id belonged to.
_PROJECT_RULE_FOLDER_DELETE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "文件夹规则不存在",
    "operation_failed": "删除文件夹规则失败",
}

# Maps Project lifecycle API stable codes to Phase 5G user-facing messages
# for project create / edit / enable-disable / archive. Unknown codes
# collapse to the matching operation-specific generic failure so internal
# details are never surfaced. Each operation has its own fallback message
# so a create failure never echoes an update-focused message, etc.
_PROJECT_LIFECYCLE_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "duplicate_project": "项目名称已存在",
    "operation_failed": "新增项目失败",
}

_PROJECT_LIFECYCLE_UPDATE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "项目不存在",
    "system_project": "系统项目不能修改",
    "duplicate_project": "项目名称已存在",
    "operation_failed": "保存项目失败",
}

_PROJECT_LIFECYCLE_TOGGLE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "项目不存在",
    "system_project": "系统项目不能修改",
    "operation_failed": "更新项目状态失败",
}

_PROJECT_LIFECYCLE_ARCHIVE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "项目不存在",
    "system_project": "系统项目不能修改",
    "operation_failed": "归档项目失败",
}


# ---------------------------------------------------------------------------
# Payload helpers.
# ---------------------------------------------------------------------------


def _project_rules_project_payload(project: dict[str, Any]) -> dict[str, Any]:
    """Build one Phase 5A Project Rules display payload.

    Phase M4: the raw ``created_by`` value is no longer surfaced to the
    frontend; only display-safe boolean flags (``is_system`` /
    ``editable`` / ``can_toggle`` / ``can_archive`` / ``is_excluded``)
    are exposed for frontend decision logic.
    """
    project = _project_rules_mapping(project)
    project_name = _project_rules_text(project.get("name"), "未知项目")
    project_enabled = _project_rules_bool(project.get("enabled"), default=True)
    is_excluded = project_name == "排除规则"
    # Phase 5G / M4: display-safe project lifecycle flags. ``is_system`` is
    # True for system/special projects (``created_by == "system"`` or
    # reserved special project names). The raw ``created_by`` value is NOT
    # surfaced via these flags or anywhere in the payload; only the boolean
    # is exposed for frontend decision logic. User projects are editable /
    # can_toggle / can_archive; system projects are not.
    is_system = (
        _project_rules_text(project.get("created_by"), "") == "system"
        or project_name in {UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT}
    )
    editable = not is_system
    can_toggle = not is_system
    can_archive = not is_system
    folder_rules = [
        _project_rules_folder_payload(rule, project_name)
        for rule in _project_rules_list(project.get("folder_rules"))
    ]
    keyword_rules = [
        _project_rules_keyword_payload(rule, project_name)
        for rule in _project_rules_list(project.get("keyword_rules"))
    ]
    folder_count = len(folder_rules)
    keyword_count = len(keyword_rules)
    rule_count = folder_count + keyword_count
    summary = _project_rules_summary(
        project_enabled=project_enabled,
        is_excluded=is_excluded,
        folder_count=folder_count,
        keyword_count=keyword_count,
    )
    return {
        "id": _project_rules_int(project.get("id")),
        "name": project_name,
        "description": _project_rules_text(project.get("description"), ""),
        "enabled": project_enabled,
        "is_excluded": is_excluded,
        "is_system": is_system,
        "editable": editable,
        "can_toggle": can_toggle,
        "can_archive": can_archive,
        "summary": summary,
        "folder_rule_count": folder_count,
        "keyword_rule_count": keyword_count,
        "rule_count": rule_count,
        "rules": [*folder_rules, *keyword_rules],
    }


def _project_lifecycle_summary(project: dict[str, Any]) -> dict[str, Any]:
    """Build the narrow project summary payload for Phase 5G lifecycle writes.

    Only exposes display-safe fields (``id`` / ``name`` / ``description`` /
    ``enabled`` / ``archived``). Never surfaces ``created_by`` /
    ``created_at`` / ``updated_at`` / raw row / traceback / SQL.
    """
    project = _project_rules_mapping(project)
    return {
        "id": _project_rules_int(project.get("id")),
        "name": _project_rules_text(project.get("name"), ""),
        "description": _project_rules_text(project.get("description"), ""),
        "enabled": _project_rules_bool(project.get("enabled"), default=True),
        "archived": _project_rules_bool(project.get("archived"), default=False),
    }


def _project_rules_folder_payload(rule: dict[str, Any], project_name: str) -> dict[str, Any]:
    rule = _project_rules_mapping(rule)
    enabled = _project_rules_bool(rule.get("enabled"), default=True)
    recursive = _project_rules_bool(rule.get("recursive"), default=True)
    scope = "包含子文件夹" if recursive else "仅直接文件"
    state = "已启用" if enabled else "已禁用"
    return {
        "kind": "folder",
        "kind_label": "文件夹",
        "id": _project_rules_int(rule.get("id")),
        "target": _project_rules_text(rule.get("folder_path"), ""),
        "enabled": enabled,
        "recursive": recursive,
        "detail": f"归属项目：{project_name} | {scope} | {state}",
    }


def _project_rules_keyword_payload(rule: dict[str, Any], project_name: str) -> dict[str, Any]:
    rule = _project_rules_mapping(rule)
    enabled = _project_rules_bool(rule.get("enabled"), default=True)
    state = "已启用" if enabled else "已禁用"
    return {
        "kind": "keyword",
        "kind_label": "关键词",
        "id": _project_rules_int(rule.get("id")),
        "target": _project_rules_text(rule.get("keyword"), ""),
        "enabled": enabled,
        "recursive": None,
        "detail": f"归属项目：{project_name} | {state}",
    }


def _project_rules_summary(
    *,
    project_enabled: bool,
    is_excluded: bool,
    folder_count: int,
    keyword_count: int,
) -> str:
    parts: list[str] = []
    if not project_enabled:
        parts.append("已禁用")
    if is_excluded:
        parts.append("命中后匿名记录")
    total = folder_count + keyword_count
    if total == 0:
        parts.append("暂无规则")
    else:
        parts.append(f"{total} 条规则：文件夹 {folder_count}，关键词 {keyword_count}")
    return " | ".join(parts)


def _project_rules_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return default


def _project_rules_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _project_rules_text(value: Any, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _project_rules_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _project_rules_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


# ---------------------------------------------------------------------------
# ProjectRulesBridgeMixin: the 12 Project Rules bridge methods.
# ---------------------------------------------------------------------------


class ProjectRulesBridgeMixin:
    """Project Rules bridge methods, split out of ``WebViewBridge``.

    The mixin is mixed into ``WebViewBridge`` in ``bridge.py`` so the 12
    method names (``get_project_rules`` / ``set_project_rule_enabled`` /
    ... / ``archive_project_for_rules``) stay on ``WebViewBridge`` and the
    frontend / tests see no API-surface change. The mixin must NOT add
    ``__init__``; it relies on the host class having a ``logger`` and the
    module-level ``logger`` defined above for exception logging.
    """

    # --- Phase 5B: Project Rules rule enable/disable foundation ---------

    def get_project_rules(self) -> dict[str, Any]:
        """Return display-safe Project Rules data for the WebView page.

        Read path: this method delegates to
        ``project_api.list_project_bindings()`` and projects the result into
        a stable display payload. It never writes projects/rules, never opens
        native dialogs, and never exposes traceback / SQL / raw exception
        details.
        """
        try:
            projects = project_api.list_project_bindings()
            return {
                "ok": True,
                "projects": [_project_rules_project_payload(project) for project in projects],
            }
        except Exception:
            logger.exception("webview bridge get_project_rules failed")
            return {"ok": False, "error": "加载项目规则失败", "projects": []}

    def set_project_rule_enabled(self, rule_type, rule_id, enabled) -> dict[str, Any]:
        """Enable/disable one existing folder or keyword rule.

        Phase 5B write path only: strict bridge validation rejects bool-as-int
        ids and non-bool enabled values before calling ``rule_api``. The bridge
        never exposes raw exceptions or backend details in the payload.
        """
        try:
            # ``isinstance(rule_type, str)`` short-circuits the set membership
            # check so unhashable non-string types (list / dict) collapse to
            # ``操作无效`` instead of being caught by the outer except and
            # reported as ``更新规则状态失败``.
            if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
                return {"ok": False, "error": "操作无效"}
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(enabled) is not bool:
                return {"ok": False, "error": "操作无效"}
            result = rule_api.set_project_rule_enabled(rule_type, rule_id, enabled)
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "rule_type": str(result.get("rule_type") or rule_type),
                    "rule_id": int(result.get("rule_id") or rule_id),
                    "enabled": bool(result.get("enabled")),
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_WRITE_MESSAGES.get(code, "更新规则状态失败"),
            }
        except Exception:
            logger.exception("webview bridge set_project_rule_enabled failed")
            return {"ok": False, "error": "更新规则状态失败"}

    # --- Phase 5C: Project Rules keyword rule creation foundation ------

    def create_project_keyword_rule(self, project_id, keyword) -> dict[str, Any]:
        """Create one new keyword rule on an existing rule-target project.

        Phase 5C write path only. Strict bridge validation rejects
        bool-as-int ``project_id``, non-int ``project_id``, non-positive
        ids, non-string ``keyword``, and whitespace-only ``keyword`` before
        calling ``rule_api.create_project_keyword_rule``. The bridge never
        exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "keyword", "id": int,
        "project_id": int, "keyword": str, "enabled": True}}`` on success
        (the narrow created-rule summary only — the frontend re-fetches the
        full Project Rules list via ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B toggle validation pattern.
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(keyword) is not str or not keyword.strip():
                return {"ok": False, "error": "操作无效"}
            # Phase 5C.1: pass the trimmed keyword to the API so the bridge
            # never forwards leading/trailing whitespace even if a future API
            # change drops the trim. Behavior-neutral: the API already trims.
            trimmed_keyword = keyword.strip()
            result = rule_api.create_project_keyword_rule(project_id, trimmed_keyword)
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "keyword",
                        "id": int(rule.get("id") or 0),
                        "project_id": int(rule.get("project_id") or project_id),
                        "keyword": str(rule.get("keyword") or ""),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_CREATE_MESSAGES.get(code, "新增关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge create_project_keyword_rule failed")
            return {"ok": False, "error": "新增关键词规则失败"}

    # --- Phase 5D: Project Rules keyword rule deletion foundation -------

    def delete_project_keyword_rule(self, rule_id) -> dict[str, Any]:
        """Delete one existing keyword rule.

        Phase 5D write path only. Strict bridge validation rejects
        bool-as-int ``rule_id``, non-int ``rule_id``, and non-positive ids
        before calling ``rule_api.delete_project_keyword_rule``. The bridge
        never exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "keyword", "id": int,
        "deleted": True}}`` on success (the narrow deleted-rule summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            result = rule_api.delete_project_keyword_rule(rule_id)
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "keyword",
                        "id": int(rule.get("id") or rule_id),
                        "deleted": bool(rule.get("deleted")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_DELETE_MESSAGES.get(code, "删除关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge delete_project_keyword_rule failed")
            return {"ok": False, "error": "删除关键词规则失败"}

    # --- Phase 5F: Project Rules keyword rule edit foundation --------

    def update_project_keyword_rule(self, rule_id, keyword) -> dict[str, Any]:
        """Update one existing keyword rule's ``keyword`` text.

        Phase 5F write path only. Strict bridge validation rejects
        bool-as-int ``rule_id``, non-int ``rule_id``, non-positive ids,
        non-string ``keyword``, and whitespace-only ``keyword`` before
        calling ``rule_api.update_project_keyword_rule``. The bridge never
        exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "keyword", "id": int,
        "project_id": int, "keyword": str, "enabled": bool}}`` on success
        (the narrow updated-rule summary only — the frontend re-fetches the
        full Project Rules list via ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C / 5D validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(keyword) is not str or not keyword.strip():
                return {"ok": False, "error": "操作无效"}
            # Pass the trimmed keyword to the API so the bridge never
            # forwards leading/trailing whitespace even if a future API
            # change drops the trim. Behavior-neutral: the API already trims.
            trimmed_keyword = keyword.strip()
            result = rule_api.update_project_keyword_rule(rule_id, trimmed_keyword)
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "keyword",
                        "id": int(rule.get("id") or rule_id),
                        "project_id": int(rule.get("project_id") or 0),
                        "keyword": str(rule.get("keyword") or ""),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_UPDATE_MESSAGES.get(code, "保存关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge update_project_keyword_rule failed")
            return {"ok": False, "error": "保存关键词规则失败"}

    # --- Phase 5E: Project Rules folder rule CRUD foundation ---------

    def create_project_folder_rule(self, project_id, folder_path, recursive) -> dict[str, Any]:
        """Create one new folder rule on an existing rule-target project.

        Phase 5E write path only. Strict bridge validation rejects
        bool-as-int ``project_id``, non-int ``project_id``, non-positive
        ids, non-string ``folder_path``, whitespace-only ``folder_path``,
        and non-bool ``recursive`` before calling
        ``rule_api.create_project_folder_rule``. The bridge never exposes
        raw exceptions, tracebacks, SQL, paths, window titles, clipboard, or
        notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "folder", "id": int,
        "project_id": int, "folder_path": str, "recursive": bool,
        "enabled": True}}`` on success (the narrow created-rule summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C / 5D validation pattern.
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(folder_path) is not str or not folder_path.strip():
                return {"ok": False, "error": "操作无效"}
            if type(recursive) is not bool:
                return {"ok": False, "error": "操作无效"}
            # Pass the trimmed folder_path to the API so the bridge never
            # forwards leading/trailing whitespace even if a future API
            # change drops the trim. Behavior-neutral: the API already trims.
            trimmed_path = folder_path.strip()
            result = rule_api.create_project_folder_rule(
                project_id, trimmed_path, recursive
            )
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "folder",
                        "id": int(rule.get("id") or 0),
                        "project_id": int(rule.get("project_id") or project_id),
                        "folder_path": str(rule.get("folder_path") or ""),
                        "recursive": bool(rule.get("recursive")),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_FOLDER_CREATE_MESSAGES.get(
                    code, "新增文件夹规则失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge create_project_folder_rule failed")
            return {"ok": False, "error": "新增文件夹规则失败"}

    def update_project_folder_rule(self, rule_id, folder_path, recursive) -> dict[str, Any]:
        """Update one existing folder rule's ``folder_path`` and ``recursive``.

        Phase 5E write path only. Strict bridge validation rejects
        bool-as-int ``rule_id``, non-int ``rule_id``, non-positive ids,
        non-string ``folder_path``, whitespace-only ``folder_path``, and
        non-bool ``recursive`` before calling
        ``rule_api.update_project_folder_rule``. The bridge never exposes
        raw exceptions, tracebacks, SQL, paths, window titles, clipboard, or
        notes in the payload. A ``rule_id`` that points at a keyword rule is
        rejected as ``文件夹规则不存在`` rather than modifying the keyword rule.

        Returns ``{"ok": True, "rule": {"kind": "folder", "id": int,
        "project_id": int, "folder_path": str, "recursive": bool,
        "enabled": True}}`` on success (the narrow updated-rule summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C / 5D validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(folder_path) is not str or not folder_path.strip():
                return {"ok": False, "error": "操作无效"}
            if type(recursive) is not bool:
                return {"ok": False, "error": "操作无效"}
            trimmed_path = folder_path.strip()
            result = rule_api.update_project_folder_rule(
                rule_id, trimmed_path, recursive
            )
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "folder",
                        "id": int(rule.get("id") or rule_id),
                        "project_id": int(rule.get("project_id") or 0),
                        "folder_path": str(rule.get("folder_path") or ""),
                        "recursive": bool(rule.get("recursive")),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_FOLDER_UPDATE_MESSAGES.get(
                    code, "保存文件夹规则失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge update_project_folder_rule failed")
            return {"ok": False, "error": "保存文件夹规则失败"}

    def delete_project_folder_rule(self, rule_id) -> dict[str, Any]:
        """Delete one existing folder rule.

        Phase 5E write path only. Strict bridge validation rejects
        bool-as-int ``rule_id``, non-int ``rule_id``, and non-positive ids
        before calling ``rule_api.delete_project_folder_rule``. The bridge
        never exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload. A ``rule_id`` that points at a
        keyword rule is rejected as ``文件夹规则不存在`` rather than deleting the
        keyword rule.

        Returns ``{"ok": True, "rule": {"kind": "folder", "id": int,
        "deleted": True}}`` on success (the narrow deleted-rule summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C / 5D validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            result = rule_api.delete_project_folder_rule(rule_id)
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "folder",
                        "id": int(rule.get("id") or rule_id),
                        "deleted": bool(rule.get("deleted")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_FOLDER_DELETE_MESSAGES.get(
                    code, "删除文件夹规则失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge delete_project_folder_rule failed")
            return {"ok": False, "error": "删除文件夹规则失败"}

    # --- Phase 5G: Project lifecycle foundation (create / edit / toggle / archive) ---

    def create_project_for_rules(self, name, description) -> dict[str, Any]:
        """Create one new user project from the Project Rules page.

        Phase 5G write path only. Strict bridge validation rejects
        non-string ``name``, whitespace-only ``name``, and non-string
        ``description`` before calling ``project_api.create_project_for_rules``.
        The bridge never exposes raw exceptions, tracebacks, SQL, paths,
        window titles, clipboard, or notes in the payload.

        Returns ``{"ok": True, "project": {"id": int, "name": str,
        "description": str, "enabled": bool, "archived": bool}}`` on
        success (the narrow created-project summary only — the frontend
        re-fetches the full Project Rules list via ``get_project_rules``
        after success) or ``{"ok": False, "error": "<chinese message>"}``
        on failure.
        """
        try:
            # ``type(...) is not str`` rejects ``bool`` / ``int`` / ``float``
            # / ``None`` / container types so a non-string name/description
            # never reaches the API. ``description`` may be empty but must
            # still be a real ``str``.
            if type(name) is not str or not name.strip():
                return {"ok": False, "error": "操作无效"}
            if type(description) is not str:
                return {"ok": False, "error": "操作无效"}
            # Pass the trimmed values to the API so the bridge never
            # forwards leading/trailing whitespace even if a future API
            # change drops the trim. Behavior-neutral: the API already trims.
            trimmed_name = name.strip()
            trimmed_description = description.strip()
            result = project_api.create_project_for_rules(
                trimmed_name, trimmed_description
            )
            if result.get("ok") is True:
                project = result.get("project") or {}
                return {
                    "ok": True,
                    "project": _project_lifecycle_summary(project),
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_LIFECYCLE_CREATE_MESSAGES.get(
                    code, "新增项目失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge create_project_for_rules failed")
            return {"ok": False, "error": "新增项目失败"}

    def update_project_for_rules(self, project_id, name, description) -> dict[str, Any]:
        """Update one existing user project's name and description.

        Phase 5G write path only. Strict bridge validation rejects
        bool-as-int ``project_id``, non-int ``project_id``, non-positive ids,
        non-string ``name``, whitespace-only ``name``, and non-string
        ``description`` before calling ``project_api.update_project_for_rules``.
        The bridge never exposes raw exceptions, tracebacks, SQL, paths,
        window titles, clipboard, or notes in the payload.

        Returns ``{"ok": True, "project": {"id": int, "name": str,
        "description": str, "enabled": bool, "archived": bool}}`` on
        success (the narrow updated-project summary only — the frontend
        re-fetches the full Project Rules list via ``get_project_rules``
        after success) or ``{"ok": False, "error": "<chinese message>"}``
        on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C / 5D / 5E validation
            # pattern.
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(name) is not str or not name.strip():
                return {"ok": False, "error": "操作无效"}
            if type(description) is not str:
                return {"ok": False, "error": "操作无效"}
            trimmed_name = name.strip()
            trimmed_description = description.strip()
            result = project_api.update_project_for_rules(
                project_id, trimmed_name, trimmed_description
            )
            if result.get("ok") is True:
                project = result.get("project") or {}
                return {
                    "ok": True,
                    "project": _project_lifecycle_summary(project),
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_LIFECYCLE_UPDATE_MESSAGES.get(
                    code, "保存项目失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge update_project_for_rules failed")
            return {"ok": False, "error": "保存项目失败"}

    def set_project_enabled_for_rules(self, project_id, enabled) -> dict[str, Any]:
        """Enable or disable one existing user project.

        Phase 5G write path only. Strict bridge validation rejects
        bool-as-int ``project_id``, non-int ``project_id``, non-positive ids,
        and non-bool ``enabled`` before calling
        ``project_api.set_project_enabled_for_rules``. The bridge never
        exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "project": {"id": int, "name": str,
        "description": str, "enabled": bool, "archived": bool}}`` on
        success (the narrow toggled-project summary only — the frontend
        re-fetches the full Project Rules list via ``get_project_rules``
        after success) or ``{"ok": False, "error": "<chinese message>"}``
        on failure.
        """
        try:
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(enabled) is not bool:
                return {"ok": False, "error": "操作无效"}
            result = project_api.set_project_enabled_for_rules(project_id, enabled)
            if result.get("ok") is True:
                project = result.get("project") or {}
                return {
                    "ok": True,
                    "project": _project_lifecycle_summary(project),
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_LIFECYCLE_TOGGLE_MESSAGES.get(
                    code, "更新项目状态失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge set_project_enabled_for_rules failed")
            return {"ok": False, "error": "更新项目状态失败"}

    def archive_project_for_rules(self, project_id) -> dict[str, Any]:
        """Archive one existing user project.

        Phase 5G write path only. Strict bridge validation rejects
        bool-as-int ``project_id``, non-int ``project_id``, and non-positive
        ids before calling ``project_api.archive_project_for_rules``. The
        bridge never exposes raw exceptions, tracebacks, SQL, paths, window
        titles, clipboard, or notes in the payload.

        Returns ``{"ok": True, "project": {"id": int, "name": str,
        "description": str, "enabled": bool, "archived": bool}}`` on
        success (the narrow archived-project summary only — the frontend
        re-fetches the full Project Rules list via ``get_project_rules``
        after success) or ``{"ok": False, "error": "<chinese message>"}``
        on failure.
        """
        try:
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            result = project_api.archive_project_for_rules(project_id)
            if result.get("ok") is True:
                project = result.get("project") or {}
                return {
                    "ok": True,
                    "project": _project_lifecycle_summary(project),
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_LIFECYCLE_ARCHIVE_MESSAGES.get(
                    code, "归档项目失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge archive_project_for_rules failed")
            return {"ok": False, "error": "归档项目失败"}


__all__ = [
    "ProjectRulesBridgeMixin",
    "_PROJECT_LIFECYCLE_ARCHIVE_MESSAGES",
    "_PROJECT_LIFECYCLE_CREATE_MESSAGES",
    "_PROJECT_LIFECYCLE_TOGGLE_MESSAGES",
    "_PROJECT_LIFECYCLE_UPDATE_MESSAGES",
    "_PROJECT_RULE_CREATE_MESSAGES",
    "_PROJECT_RULE_DELETE_MESSAGES",
    "_PROJECT_RULE_FOLDER_CREATE_MESSAGES",
    "_PROJECT_RULE_FOLDER_DELETE_MESSAGES",
    "_PROJECT_RULE_FOLDER_UPDATE_MESSAGES",
    "_PROJECT_RULE_UPDATE_MESSAGES",
    "_PROJECT_RULE_WRITE_MESSAGES",
    "_project_lifecycle_summary",
    "_project_rules_bool",
    "_project_rules_folder_payload",
    "_project_rules_int",
    "_project_rules_keyword_payload",
    "_project_rules_list",
    "_project_rules_mapping",
    "_project_rules_project_payload",
    "_project_rules_summary",
    "_project_rules_text",
]
