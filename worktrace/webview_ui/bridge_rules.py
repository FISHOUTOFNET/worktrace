"""Project Rules WebView bridge input and capability boundary."""

from __future__ import annotations

import logging
from typing import Any

from ..api import project_api, rule_api, rule_history_api
from .project_rules_presenter import (
    _EXCLUDED_FOLDER_RULE_CREATE_MESSAGES,
    _EXCLUDED_KEYWORD_RULE_CREATE_MESSAGES,
    _PROJECT_LIFECYCLE_ARCHIVE_MESSAGES,
    _PROJECT_LIFECYCLE_CREATE_MESSAGES,
    _PROJECT_LIFECYCLE_DELETE_MESSAGES,
    _PROJECT_LIFECYCLE_TOGGLE_MESSAGES,
    _PROJECT_LIFECYCLE_UPDATE_MESSAGES,
    _PROJECT_RULE_BACKFILL_MESSAGES,
    _PROJECT_RULE_BATCH_APPLY_MESSAGES,
    _PROJECT_RULE_BATCH_PREVIEW_MESSAGES,
    _PROJECT_RULE_BATCH_TOGGLE_MESSAGES,
    _PROJECT_RULE_CREATE_MESSAGES,
    _PROJECT_RULE_DELETE_MESSAGES,
    _PROJECT_RULE_FOLDER_CREATE_MESSAGES,
    _PROJECT_RULE_FOLDER_DELETE_MESSAGES,
    _PROJECT_RULE_FOLDER_UPDATE_MESSAGES,
    _PROJECT_RULE_IMPACT_PREVIEW_MESSAGES,
    _PROJECT_RULE_UPDATE_MESSAGES,
    _PROJECT_RULE_WRITE_MESSAGES,
    _project_lifecycle_summary,
    _project_rules_project_payload,
)

logger = logging.getLogger(__name__)
_APPLY_TO_HISTORY_UNSET = object()


# ProjectRulesBridgeMixin: Project Rules bridge methods.


class ProjectRulesBridgeMixin:
    """Project Rules bridge methods.

    Mixed into ``WebViewBridge`` in ``bridge.py`` so the Project Rules
    method names (``get_project_rules`` / ``set_project_rule_enabled`` /
    ... / ``archive_project_for_rules``) stay on ``WebViewBridge``. The
    mixin must NOT add ``__init__``; it relies on the host class having a
    ``logger`` and the module-level ``logger`` defined above for exception
    logging.
    """


    def get_project_rules(self) -> dict[str, Any]:
        """Return display-safe Project Rules data for the WebView page.

        Read path: this method delegates to
        ``project_api.list_project_bindings()`` and projects the result into
        a stable display payload. It never writes projects/rules, never opens
        native dialogs, and never exposes traceback / SQL / raw exception
        details.
        """
        try:
            rows = project_api.list_project_bindings()
            projected = [_project_rules_project_payload(project) for project in rows]
            excluded = None
            projects = []
            for project in projected:
                if project.get("is_excluded"):
                    excluded = project
                else:
                    projects.append(project)
            return {
                "ok": True,
                "projects": projects,
                "advanced": {
                    "excluded_rules_enabled": bool(excluded and excluded.get("enabled")),
                    "excluded_project": excluded,
                    "excluded_rules": (excluded or {}).get("rules", []),
                },
            }
        except Exception:
            logger.exception("webview bridge get_project_rules failed")
            return {
                "ok": False,
                "error": "加载项目规则失败",
                "projects": [],
                "advanced": {
                    "excluded_rules_enabled": False,
                    "excluded_project": None,
                    "excluded_rules": [],
                },
            }

    def set_project_rule_enabled(self, rule_type, rule_id, enabled) -> dict[str, Any]:
        """Enable/disable one existing folder or keyword rule.

        Write path only: strict bridge validation rejects bool-as-int
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


    def create_project_keyword_rule(self, project_id, keyword) -> dict[str, Any]:
        """Create one new keyword rule on an existing rule-target project.

        Write path only. Strict bridge validation rejects
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
            # one check, matching the toggle validation pattern.
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(keyword) is not str or not keyword.strip():
                return {"ok": False, "error": "操作无效"}
            # Pass the trimmed keyword to the API so the bridge never
            # forwards leading/trailing whitespace even if a future API
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


    def delete_project_keyword_rule(self, rule_id, apply_to_history=_APPLY_TO_HISTORY_UNSET) -> dict[str, Any]:
        """Delete one existing keyword rule.

        Write path only. Strict bridge validation rejects
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
            # one check, matching the shared rule-id validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if apply_to_history is not _APPLY_TO_HISTORY_UNSET and type(apply_to_history) is not bool:
                return {"ok": False, "error": "操作无效"}
            result = (
                rule_api.delete_project_keyword_rule(rule_id)
                if apply_to_history is _APPLY_TO_HISTORY_UNSET
                else rule_api.delete_project_keyword_rule(rule_id, apply_to_history)
            )
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                summary = {
                    "kind": "keyword",
                    "id": int(rule.get("id") or rule_id),
                    "deleted": bool(rule.get("deleted")),
                }
                if apply_to_history is not _APPLY_TO_HISTORY_UNSET:
                    summary.update({
                        "history_updated": bool(rule.get("history_updated")),
                        "updated_count": int(rule.get("updated_count") or 0),
                    })
                return {
                    "ok": True,
                    "rule": summary,
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_DELETE_MESSAGES.get(code, "删除关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge delete_project_keyword_rule failed")
            return {"ok": False, "error": "删除关键词规则失败"}


    def update_project_keyword_rule(self, rule_id, keyword) -> dict[str, Any]:
        """Update one existing keyword rule's ``keyword`` text.

        Write path only. Strict bridge validation rejects
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
            # one check, matching the shared rule-id validation pattern.
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


    def create_project_folder_rule(self, project_id, folder_path, recursive) -> dict[str, Any]:
        """Create one new folder rule on an existing rule-target project.

        Write path only. Strict bridge validation rejects
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
            # one check, matching the shared rule-id validation pattern.
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


    def create_excluded_keyword_rule(self, keyword) -> dict[str, Any]:
        """Create one new keyword rule on the special ``排除规则`` project.

        Write path only. This is the dedicated excluded-rule
        creation entry: it does NOT accept any ``project_id`` from the
        caller, so the frontend cannot inject an arbitrary project_id.
        The API facade internally resolves the ``EXCLUDED_PROJECT``
        project_id via the require-only system catalog query. Strict bridge
        validation rejects non-string ``keyword`` and whitespace-only
        ``keyword`` before calling
        ``rule_api.create_excluded_keyword_rule_for_webview``. The bridge
        never exposes raw exceptions, tracebacks, SQL, paths, window
        titles, clipboard, or notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "keyword", "id": int,
        "project_id": int, "keyword": str, "enabled": True}}`` on success
        or ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            if type(keyword) is not str or not keyword.strip():
                return {"ok": False, "error": "操作无效"}
            trimmed_keyword = keyword.strip()
            result = rule_api.create_excluded_keyword_rule_for_webview(trimmed_keyword)
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "keyword",
                        "id": int(rule.get("id") or 0),
                        "project_id": int(rule.get("project_id") or 0),
                        "keyword": str(rule.get("keyword") or ""),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _EXCLUDED_KEYWORD_RULE_CREATE_MESSAGES.get(
                    code, "新增排除关键词规则失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge create_excluded_keyword_rule failed")
            return {"ok": False, "error": "新增排除关键词规则失败"}

    def create_excluded_folder_rule(self, folder_path, recursive) -> dict[str, Any]:
        """Create one new folder rule on the special ``排除规则`` project.

        Write path only. This is the dedicated excluded-rule
        creation entry: it does NOT accept any ``project_id`` from the
        caller, so the frontend cannot inject an arbitrary project_id.
        The API facade internally resolves the ``EXCLUDED_PROJECT``
        project_id via the require-only system catalog query. Strict bridge
        validation rejects non-string ``folder_path``, whitespace-only
        ``folder_path``, and non-bool ``recursive`` before calling
        ``rule_api.create_excluded_folder_rule_for_webview``. The bridge
        never exposes raw exceptions, tracebacks, SQL, paths, window
        titles, clipboard, or notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "folder", "id": int,
        "project_id": int, "folder_path": str, "recursive": bool,
        "enabled": True}}`` on success or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            if type(folder_path) is not str or not folder_path.strip():
                return {"ok": False, "error": "操作无效"}
            if type(recursive) is not bool:
                return {"ok": False, "error": "操作无效"}
            trimmed_path = folder_path.strip()
            result = rule_api.create_excluded_folder_rule_for_webview(
                trimmed_path, recursive
            )
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "folder",
                        "id": int(rule.get("id") or 0),
                        "project_id": int(rule.get("project_id") or 0),
                        "folder_path": str(rule.get("folder_path") or ""),
                        "recursive": bool(rule.get("recursive")),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _EXCLUDED_FOLDER_RULE_CREATE_MESSAGES.get(
                    code, "新增排除文件夹规则失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge create_excluded_folder_rule failed")
            return {"ok": False, "error": "新增排除文件夹规则失败"}

    def update_project_folder_rule(self, rule_id, folder_path, recursive) -> dict[str, Any]:
        """Update one existing folder rule's ``folder_path`` and ``recursive``.

        Write path only. Strict bridge validation rejects
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
            # one check, matching the shared rule-id validation pattern.
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

    def delete_project_folder_rule(self, rule_id, apply_to_history=_APPLY_TO_HISTORY_UNSET) -> dict[str, Any]:
        """Delete one existing folder rule.

        Write path only. Strict bridge validation rejects
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
            # one check, matching the shared rule-id validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if apply_to_history is not _APPLY_TO_HISTORY_UNSET and type(apply_to_history) is not bool:
                return {"ok": False, "error": "操作无效"}
            result = (
                rule_api.delete_project_folder_rule(rule_id)
                if apply_to_history is _APPLY_TO_HISTORY_UNSET
                else rule_api.delete_project_folder_rule(rule_id, apply_to_history)
            )
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                summary = {
                    "kind": "folder",
                    "id": int(rule.get("id") or rule_id),
                    "deleted": bool(rule.get("deleted")),
                }
                if apply_to_history is not _APPLY_TO_HISTORY_UNSET:
                    summary.update({
                        "history_updated": bool(rule.get("history_updated")),
                        "updated_count": int(rule.get("updated_count") or 0),
                    })
                return {
                    "ok": True,
                    "rule": summary,
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


    def create_project_for_rules(
        self,
        name,
        description,
        language="中文",
    ) -> dict[str, Any]:
        """Create one new user project from the Project Rules page.

        Write path only. Strict bridge validation rejects
        non-string ``name``, whitespace-only ``name``, and non-string
        ``description`` / ``language`` before calling
        ``project_api.create_project_for_rules``.
        The bridge never exposes raw exceptions, tracebacks, SQL, paths,
        window titles, clipboard, or notes in the payload.
        Returns ``{"ok": True, "project": {"id": int, "name": str,
        "description": str, "language": str, "enabled": bool,
        "archived": bool}}`` on success (the narrow created-project summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
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
            if type(language) is not str:
                return {"ok": False, "error": "操作无效"}
            # Pass the trimmed values to the API so the bridge never
            # forwards leading/trailing whitespace even if a future API
            # change drops the trim. Behavior-neutral: the API already trims.
            trimmed_name = name.strip()
            trimmed_description = description.strip()
            trimmed_language = language.strip() or "中文"
            result = project_api.create_project_for_rules(
                trimmed_name, trimmed_description, trimmed_language
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

    def update_project_for_rules(
        self,
        project_id,
        name,
        description,
        language="中文",
    ) -> dict[str, Any]:
        """Update one existing user project's name and description.

        Write path only. Strict bridge validation rejects
        bool-as-int ``project_id``, non-int ``project_id``, non-positive ids,
        non-string ``name``, whitespace-only ``name``, and non-string
        ``description`` / ``language`` before calling
        ``project_api.update_project_for_rules``.
        The bridge never exposes raw exceptions, tracebacks, SQL, paths,
        window titles, clipboard, or notes in the payload.

        Returns ``{"ok": True, "project": {"id": int, "name": str,
        "description": str, "language": str, "enabled": bool,
        "archived": bool}}`` on success (the narrow updated-project summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the shared rule-id validation pattern.
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(name) is not str or not name.strip():
                return {"ok": False, "error": "操作无效"}
            if type(description) is not str:
                return {"ok": False, "error": "操作无效"}
            if type(language) is not str:
                return {"ok": False, "error": "操作无效"}
            trimmed_name = name.strip()
            trimmed_description = description.strip()
            trimmed_language = language.strip() or "中文"
            result = project_api.update_project_for_rules(
                project_id, trimmed_name, trimmed_description, trimmed_language
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

        Write path only. Strict bridge validation rejects
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

    def set_excluded_rules_enabled(self, enabled) -> dict[str, Any]:
        """Enable or disable the special excluded-rules project."""
        try:
            if type(enabled) is not bool:
                return {"ok": False, "error": "操作无效"}
            result = project_api.set_excluded_rules_enabled(enabled)
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
                    code, "更新排除规则状态失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge set_excluded_rules_enabled failed")
            return {"ok": False, "error": "更新排除规则状态失败"}

    def archive_project_for_rules(self, project_id) -> dict[str, Any]:
        """Archive one existing user project.

        Write path only. Strict bridge validation rejects
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

    def delete_project_for_rules(self, project_id) -> dict[str, Any]:
        """Soft-delete one user project from the Project Rules page."""
        try:
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            result = project_api.delete_project_for_rules(project_id)
            if result.get("ok") is True:
                project = result.get("project") or {}
                return {
                    "ok": True,
                    "project": {
                        "id": int(project.get("id") or project_id),
                        "deleted": bool(project.get("deleted")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_LIFECYCLE_DELETE_MESSAGES.get(code, "删除项目失败"),
            }
        except Exception:
            logger.exception("webview bridge delete_project_for_rules failed")
            return {"ok": False, "error": "删除项目失败"}


    def preview_project_rule_impact(self, rule_type, rule_id) -> dict[str, Any]:
        """Preview the impact of applying one existing folder / keyword rule.

        Read path only. Strict bridge validation rejects non-string
        ``rule_type``, unknown rule types, bool-as-int ``rule_id``,
        non-int ``rule_id``, and non-positive ids before calling
        ``rule_history_api.preview_project_rule_impact``. The bridge never exposes
        raw exceptions, tracebacks, SQL, paths, window titles, clipboard, or
        notes in the payload.

        Returns ``{"ok": True, "impact": {...}}`` on success (the narrow
        impact payload: ``rule`` summary, ``counts``, and up to 20
        display-safe ``samples``) or ``{"ok": False, "error": "<chinese
        message>"}`` on failure. Preview never refreshes the Project Rules
        list and never writes anything.
        """
        try:
            # ``isinstance(rule_type, str)`` short-circuits the set membership
            # check so unhashable non-string types (list / dict) collapse to
            # ``操作无效`` instead of leaking a ``TypeError``.
            if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
                return {"ok": False, "error": "操作无效"}
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            result = rule_history_api.preview_project_rule_impact(rule_type, rule_id)
            if result.get("ok") is True:
                return {"ok": True, "impact": result.get("impact") or {}}
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_IMPACT_PREVIEW_MESSAGES.get(
                    code, "预览规则影响失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge preview_project_rule_impact failed")
            return {"ok": False, "error": "预览规则影响失败"}

    def backfill_project_rule(self, rule_type, rule_id) -> dict[str, Any]:
        """Apply one existing enabled folder / keyword rule to eligible history.

        Write path only. Strict bridge validation rejects non-string
        ``rule_type``, unknown rule types, bool-as-int ``rule_id``,
        non-int ``rule_id``, and non-positive ids before calling
        ``rule_history_api.backfill_project_rule``. The bridge never exposes raw
        exceptions, tracebacks, SQL, paths, window titles, clipboard, or notes
        in the payload.

        Returns ``{"ok": True, "result": {...}}`` on success (the narrow
        result payload: ``updated_count`` and skip/count fields + rule
        summary) or ``{"ok": False, "error": "<chinese message>"}`` on
        failure. On success the frontend re-fetches the full Project Rules
        list via ``get_project_rules``; on failure the list is not refreshed.
        Backfill never overwrites manual records and is capped at 100 updates
        per call (``too_many_matches`` writes nothing).
        """
        try:
            if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
                return {"ok": False, "error": "操作无效"}
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            result = rule_history_api.backfill_project_rule(rule_type, rule_id)
            if result.get("ok") is True:
                return {"ok": True, "result": result.get("result") or {}}
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_BACKFILL_MESSAGES.get(code, "应用规则失败"),
            }
        except Exception:
            logger.exception("webview bridge backfill_project_rule failed")
            return {"ok": False, "error": "应用规则失败"}


    def _validate_batch_rules(self, rules) -> str | None:
        """Strict bridge-layer validation for the ``rules`` batch input.

        Returns ``None`` when the input is a non-empty list of valid
        ``{"rule_type": "folder" | "keyword", "rule_id": positive int}``
        dicts, otherwise returns the stable code ``"invalid_input"``.

        Mirrors the API / service validation so a malformed payload never
        reaches ``rule_api``: bool-as-int ids, non-int ids, non-positive
        ids, unknown rule types, non-dict items, and non-list inputs all
        collapse to ``invalid_input`` here. De-duplication and the
        ``too_many_rules`` cap are enforced by the service layer (the
        bridge does not need to re-count).
        """

        if not isinstance(rules, list) or not rules:
            return "invalid_input"
        for item in rules:
            if not isinstance(item, dict):
                return "invalid_input"
            rule_type = item.get("rule_type")
            rule_id = item.get("rule_id")
            if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
                return "invalid_input"
            if type(rule_id) is not int or rule_id <= 0:
                return "invalid_input"
        return None

    def preview_project_rules_batch_impact(self, rules) -> dict[str, Any]:
        """Read-only aggregate impact preview across the selected rules.

        Read path only. Strict bridge validation rejects non-list
        ``rules``, empty lists, non-dict items, unknown rule types, and
        bool-as-int / non-int / non-positive ``rule_id`` values before
        calling ``rule_history_api.preview_project_rules_batch_impact``. The bridge
        never exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "impact": {...}}`` on success (the narrow
        impact payload: ``rules`` per-rule summaries, aggregate ``counts``,
        and up to 20 display-safe ``samples``) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure. Preview
        never refreshes the Project Rules list and never writes anything.
        """

        try:
            invalid = self._validate_batch_rules(rules)
            if invalid is not None:
                return {"ok": False, "error": "操作无效"}
            result = rule_history_api.preview_project_rules_batch_impact(rules)
            if result.get("ok") is True:
                return {"ok": True, "impact": result.get("impact") or {}}
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_BATCH_PREVIEW_MESSAGES.get(
                    code, "批量预览失败"
                ),
            }
        except Exception:
            logger.exception(
                "webview bridge preview_project_rules_batch_impact failed"
            )
            return {"ok": False, "error": "批量预览失败"}

    def backfill_project_rules_batch(self, rules) -> dict[str, Any]:
        """Apply the selected enabled rules to eligible history in one batch.

        Write path only. Strict bridge validation rejects non-list
        ``rules``, empty lists, non-dict items, unknown rule types, and
        bool-as-int / non-int / non-positive ``rule_id`` values before
        calling ``rule_history_api.backfill_project_rules_batch``. The bridge never
        exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "result": {...}}`` on success (the narrow
        result payload: aggregate counts + per-rule summaries; no raw
        activity rows) or ``{"ok": False, "error": "<chinese message>"}``
        on failure. The whole batch is all-or-nothing: any preflight
        failure (``not_found`` / ``rule_disabled`` / ``project_not_available``)
        or cap exceedance (``too_many_matches``) writes nothing. On success
        the frontend re-fetches the full Project Rules list via
        ``get_project_rules``; on failure the list is not refreshed.
        """

        try:
            invalid = self._validate_batch_rules(rules)
            if invalid is not None:
                return {"ok": False, "error": "操作无效"}
            result = rule_history_api.backfill_project_rules_batch(rules)
            if result.get("ok") is True:
                return {"ok": True, "result": result.get("result") or {}}
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_BATCH_APPLY_MESSAGES.get(
                    code, "批量应用失败"
                ),
            }
        except Exception:
            logger.exception(
                "webview bridge backfill_project_rules_batch failed"
            )
            return {"ok": False, "error": "批量应用失败"}

    def set_project_rules_batch_enabled(self, rules, enabled) -> dict[str, Any]:
        """Enable or disable every selected rule in one all-or-nothing batch.

        Write path only. Strict bridge validation rejects non-list
        ``rules``, empty lists, non-dict items, unknown rule types,
        bool-as-int / non-int / non-positive ``rule_id`` values, and
        non-bool ``enabled`` before calling
        ``rule_history_api.set_project_rules_batch_enabled``. The bridge never
        exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "result": {...}}`` on success (the narrow
        result payload: per-rule summaries + ``enabled`` bool + ``count``)
        or ``{"ok": False, "error": "<chinese message>"}`` on failure. The
        whole batch is all-or-nothing: any missing rule (``not_found``)
        writes nothing. On success the frontend re-fetches the full Project
        Rules list via ``get_project_rules``; on failure the list is not
        refreshed.
        """

        try:
            invalid = self._validate_batch_rules(rules)
            if invalid is not None:
                return {"ok": False, "error": "操作无效"}
            if type(enabled) is not bool:
                return {"ok": False, "error": "操作无效"}
            result = rule_history_api.set_project_rules_batch_enabled(rules, enabled)
            if result.get("ok") is True:
                return {"ok": True, "result": result.get("result") or {}}
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_BATCH_TOGGLE_MESSAGES.get(
                    code, "批量操作失败"
                ),
            }
        except Exception:
            logger.exception(
                "webview bridge set_project_rules_batch_enabled failed"
            )
            return {"ok": False, "error": "批量操作失败"}

    def automatic_rules_status(self) -> dict[str, Any]:
        """Return a display-safe status payload for the automatic-rules engine.

        Read path only. The Project Rules page uses this to render
        a status note explaining that enabled folder / keyword rules are
        automatically applied to future eligible closed activities. The
        payload is intentionally narrow: it only carries boolean / string
        fields the frontend needs. It never exposes raw rule rows, project
        rows, window titles, file paths, notes, clipboard text, SQL, or
        tracebacks.

        Returns ``{"ok": True, "status": {...}}`` on success or
        ``{"ok": False, "error": "加载自动规则状态失败"}`` on unexpected
        failure. Always succeeds under normal operation — the underlying
        ``rule_automation_service`` is a thin documented facade over the
        existing inference path and performs no DB access.
        """

        try:
            result = rule_history_api.automatic_rules_status()
            if result.get("ok") is True:
                return {"ok": True, "status": result.get("status") or {}}
            # ``automatic_rules_status`` always returns ok unless something
            # very unexpected happened; collapse to the generic load failure.
            return {"ok": False, "error": "加载自动规则状态失败"}
        except Exception:
            logger.exception("webview bridge automatic_rules_status failed")
            return {"ok": False, "error": "加载自动规则状态失败"}


__all__ = ["ProjectRulesBridgeMixin"]
