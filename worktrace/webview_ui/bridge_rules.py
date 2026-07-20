"""Project Rules WebView bridge input and capability boundary."""

from __future__ import annotations

import logging
from typing import Any, Callable

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


def _valid_id(value: object) -> bool:
    return type(value) is int and int(value) > 0


def _valid_rule_type(value: object) -> bool:
    return isinstance(value, str) and value in {"folder", "keyword"}


def _message(result: dict[str, Any], messages: dict[str, str], fallback: str) -> str:
    return messages.get(str(result.get("error") or "operation_failed"), fallback)


def _keyword_summary(rule: dict[str, Any], fallback_id: int = 0) -> dict[str, Any]:
    return {
        "kind": "keyword",
        "id": int(rule.get("id") or fallback_id),
        "project_id": int(rule.get("project_id") or 0),
        "keyword": str(rule.get("keyword") or ""),
        "enabled": bool(rule.get("enabled")),
    }


def _folder_summary(rule: dict[str, Any], fallback_id: int = 0) -> dict[str, Any]:
    return {
        "kind": "folder",
        "id": int(rule.get("id") or fallback_id),
        "project_id": int(rule.get("project_id") or 0),
        "folder_path": str(rule.get("folder_path") or ""),
        "recursive": bool(rule.get("recursive")),
        "enabled": bool(rule.get("enabled")),
    }


class ProjectRulesBridgeMixin:
    """Display-safe Project Rules bridge with exact current-only inputs."""

    def get_project_rules(self) -> dict[str, Any]:
        try:
            projected = [
                _project_rules_project_payload(project)
                for project in project_api.list_project_bindings()
            ]
            excluded = next(
                (project for project in projected if project.get("is_excluded")),
                None,
            )
            return {
                "ok": True,
                "projects": [
                    project for project in projected if not project.get("is_excluded")
                ],
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

    def set_project_rule_enabled(
        self,
        rule_type,
        rule_id,
        enabled,
    ) -> dict[str, Any]:
        if not _valid_rule_type(rule_type) or not _valid_id(rule_id) or type(enabled) is not bool:
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.set_project_rule_enabled(rule_type, rule_id, enabled)
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "rule_type": str(result.get("rule_type") or rule_type),
                    "rule_id": int(result.get("rule_id") or rule_id),
                    "enabled": bool(result.get("enabled")),
                }
            return {
                "ok": False,
                "error": _message(result, _PROJECT_RULE_WRITE_MESSAGES, "更新规则状态失败"),
            }
        except Exception:
            logger.exception("webview bridge set_project_rule_enabled failed")
            return {"ok": False, "error": "更新规则状态失败"}

    def create_project_keyword_rule(self, project_id, keyword) -> dict[str, Any]:
        if not _valid_id(project_id) or type(keyword) is not str or not keyword.strip():
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.create_project_keyword_rule(project_id, keyword.strip())
            if result.get("ok") is True:
                rule = dict(result.get("rule") or {})
                summary = _keyword_summary(rule)
                summary["project_id"] = int(rule.get("project_id") or project_id)
                return {"ok": True, "rule": summary}
            return {
                "ok": False,
                "error": _message(result, _PROJECT_RULE_CREATE_MESSAGES, "新增关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge create_project_keyword_rule failed")
            return {"ok": False, "error": "新增关键词规则失败"}

    def delete_project_keyword_rule(
        self,
        rule_id,
        apply_to_history,
    ) -> dict[str, Any]:
        if not _valid_id(rule_id) or type(apply_to_history) is not bool:
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.delete_project_keyword_rule(rule_id, apply_to_history)
            if result.get("ok") is True:
                rule = dict(result.get("rule") or {})
                return {
                    "ok": True,
                    "rule": {
                        "kind": "keyword",
                        "id": int(rule.get("id") or rule_id),
                        "deleted": bool(rule.get("deleted")),
                        "history_updated": bool(rule.get("history_updated")),
                        "updated_count": int(rule.get("updated_count") or 0),
                    },
                }
            return {
                "ok": False,
                "error": _message(result, _PROJECT_RULE_DELETE_MESSAGES, "删除关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge delete_project_keyword_rule failed")
            return {"ok": False, "error": "删除关键词规则失败"}

    def update_project_keyword_rule(self, rule_id, keyword) -> dict[str, Any]:
        if not _valid_id(rule_id) or type(keyword) is not str or not keyword.strip():
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.update_project_keyword_rule(rule_id, keyword.strip())
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "rule": _keyword_summary(dict(result.get("rule") or {}), rule_id),
                }
            return {
                "ok": False,
                "error": _message(result, _PROJECT_RULE_UPDATE_MESSAGES, "保存关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge update_project_keyword_rule failed")
            return {"ok": False, "error": "保存关键词规则失败"}

    def create_project_folder_rule(
        self,
        project_id,
        folder_path,
        recursive,
    ) -> dict[str, Any]:
        if (
            not _valid_id(project_id)
            or type(folder_path) is not str
            or not folder_path.strip()
            or type(recursive) is not bool
        ):
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.create_project_folder_rule(
                project_id,
                folder_path.strip(),
                recursive,
            )
            if result.get("ok") is True:
                rule = dict(result.get("rule") or {})
                summary = _folder_summary(rule)
                summary["project_id"] = int(rule.get("project_id") or project_id)
                return {"ok": True, "rule": summary}
            return {
                "ok": False,
                "error": _message(
                    result,
                    _PROJECT_RULE_FOLDER_CREATE_MESSAGES,
                    "新增文件夹规则失败",
                ),
            }
        except Exception:
            logger.exception("webview bridge create_project_folder_rule failed")
            return {"ok": False, "error": "新增文件夹规则失败"}

    def create_excluded_keyword_rule(self, keyword) -> dict[str, Any]:
        if type(keyword) is not str or not keyword.strip():
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.create_excluded_keyword_rule_for_webview(keyword.strip())
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "rule": _keyword_summary(dict(result.get("rule") or {})),
                }
            return {
                "ok": False,
                "error": _message(
                    result,
                    _EXCLUDED_KEYWORD_RULE_CREATE_MESSAGES,
                    "新增排除关键词规则失败",
                ),
            }
        except Exception:
            logger.exception("webview bridge create_excluded_keyword_rule failed")
            return {"ok": False, "error": "新增排除关键词规则失败"}

    def create_excluded_folder_rule(
        self,
        folder_path,
        recursive,
    ) -> dict[str, Any]:
        if (
            type(folder_path) is not str
            or not folder_path.strip()
            or type(recursive) is not bool
        ):
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.create_excluded_folder_rule_for_webview(
                folder_path.strip(),
                recursive,
            )
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "rule": _folder_summary(dict(result.get("rule") or {})),
                }
            return {
                "ok": False,
                "error": _message(
                    result,
                    _EXCLUDED_FOLDER_RULE_CREATE_MESSAGES,
                    "新增排除文件夹规则失败",
                ),
            }
        except Exception:
            logger.exception("webview bridge create_excluded_folder_rule failed")
            return {"ok": False, "error": "新增排除文件夹规则失败"}

    def update_project_folder_rule(
        self,
        rule_id,
        folder_path,
        recursive,
    ) -> dict[str, Any]:
        if (
            not _valid_id(rule_id)
            or type(folder_path) is not str
            or not folder_path.strip()
            or type(recursive) is not bool
        ):
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.update_project_folder_rule(
                rule_id,
                folder_path.strip(),
                recursive,
            )
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "rule": _folder_summary(dict(result.get("rule") or {}), rule_id),
                }
            return {
                "ok": False,
                "error": _message(
                    result,
                    _PROJECT_RULE_FOLDER_UPDATE_MESSAGES,
                    "保存文件夹规则失败",
                ),
            }
        except Exception:
            logger.exception("webview bridge update_project_folder_rule failed")
            return {"ok": False, "error": "保存文件夹规则失败"}

    def delete_project_folder_rule(
        self,
        rule_id,
        apply_to_history,
    ) -> dict[str, Any]:
        if not _valid_id(rule_id) or type(apply_to_history) is not bool:
            return {"ok": False, "error": "操作无效"}
        try:
            result = rule_api.delete_project_folder_rule(rule_id, apply_to_history)
            if result.get("ok") is True:
                rule = dict(result.get("rule") or {})
                return {
                    "ok": True,
                    "rule": {
                        "kind": "folder",
                        "id": int(rule.get("id") or rule_id),
                        "deleted": bool(rule.get("deleted")),
                        "history_updated": bool(rule.get("history_updated")),
                        "updated_count": int(rule.get("updated_count") or 0),
                    },
                }
            return {
                "ok": False,
                "error": _message(
                    result,
                    _PROJECT_RULE_FOLDER_DELETE_MESSAGES,
                    "删除文件夹规则失败",
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
        if (
            type(name) is not str
            or not name.strip()
            or type(description) is not str
            or type(language) is not str
        ):
            return {"ok": False, "error": "操作无效"}
        try:
            result = project_api.create_project_for_rules(
                name.strip(),
                description.strip(),
                language.strip() or "中文",
            )
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "project": _project_lifecycle_summary(result.get("project") or {}),
                }
            return {
                "ok": False,
                "error": _message(
                    result,
                    _PROJECT_LIFECYCLE_CREATE_MESSAGES,
                    "新增项目失败",
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
        if (
            not _valid_id(project_id)
            or type(name) is not str
            or not name.strip()
            or type(description) is not str
            or type(language) is not str
        ):
            return {"ok": False, "error": "操作无效"}
        try:
            result = project_api.update_project_for_rules(
                project_id,
                name.strip(),
                description.strip(),
                language.strip() or "中文",
            )
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "project": _project_lifecycle_summary(result.get("project") or {}),
                }
            return {
                "ok": False,
                "error": _message(
                    result,
                    _PROJECT_LIFECYCLE_UPDATE_MESSAGES,
                    "保存项目失败",
                ),
            }
        except Exception:
            logger.exception("webview bridge update_project_for_rules failed")
            return {"ok": False, "error": "保存项目失败"}

    def set_project_enabled_for_rules(self, project_id, enabled) -> dict[str, Any]:
        if not _valid_id(project_id) or type(enabled) is not bool:
            return {"ok": False, "error": "操作无效"}
        return self._project_toggle(
            lambda: project_api.set_project_enabled_for_rules(project_id, enabled),
            "更新项目状态失败",
        )

    def set_excluded_rules_enabled(self, enabled) -> dict[str, Any]:
        if type(enabled) is not bool:
            return {"ok": False, "error": "操作无效"}
        return self._project_toggle(
            lambda: project_api.set_excluded_rules_enabled(enabled),
            "更新排除规则状态失败",
        )

    def _project_toggle(
        self,
        operation: Callable[[], dict[str, Any]],
        fallback: str,
    ) -> dict[str, Any]:
        try:
            result = operation()
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "project": _project_lifecycle_summary(result.get("project") or {}),
                }
            return {
                "ok": False,
                "error": _message(result, _PROJECT_LIFECYCLE_TOGGLE_MESSAGES, fallback),
            }
        except Exception:
            logger.exception("webview bridge project toggle failed")
            return {"ok": False, "error": fallback}

    def archive_project_for_rules(self, project_id) -> dict[str, Any]:
        if not _valid_id(project_id):
            return {"ok": False, "error": "操作无效"}
        try:
            result = project_api.archive_project_for_rules(project_id)
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "project": _project_lifecycle_summary(result.get("project") or {}),
                }
            return {
                "ok": False,
                "error": _message(
                    result,
                    _PROJECT_LIFECYCLE_ARCHIVE_MESSAGES,
                    "归档项目失败",
                ),
            }
        except Exception:
            logger.exception("webview bridge archive_project_for_rules failed")
            return {"ok": False, "error": "归档项目失败"}

    def delete_project_for_rules(self, project_id) -> dict[str, Any]:
        if not _valid_id(project_id):
            return {"ok": False, "error": "操作无效"}
        try:
            result = project_api.delete_project_for_rules(project_id)
            if result.get("ok") is True:
                project = dict(result.get("project") or {})
                return {
                    "ok": True,
                    "project": {
                        "id": int(project.get("id") or project_id),
                        "deleted": bool(project.get("deleted")),
                    },
                }
            return {
                "ok": False,
                "error": _message(
                    result,
                    _PROJECT_LIFECYCLE_DELETE_MESSAGES,
                    "删除项目失败",
                ),
            }
        except Exception:
            logger.exception("webview bridge delete_project_for_rules failed")
            return {"ok": False, "error": "删除项目失败"}

    def preview_project_rule_impact(self, rule_type, rule_id) -> dict[str, Any]:
        return self._single_rule_history_operation(
            rule_type,
            rule_id,
            rule_history_api.preview_project_rule_impact,
            "impact",
            _PROJECT_RULE_IMPACT_PREVIEW_MESSAGES,
            "预览规则影响失败",
        )

    def backfill_project_rule(self, rule_type, rule_id) -> dict[str, Any]:
        return self._single_rule_history_operation(
            rule_type,
            rule_id,
            rule_history_api.backfill_project_rule,
            "result",
            _PROJECT_RULE_BACKFILL_MESSAGES,
            "应用规则失败",
        )

    def _single_rule_history_operation(
        self,
        rule_type,
        rule_id,
        operation: Callable[[str, int], dict[str, Any]],
        payload_key: str,
        messages: dict[str, str],
        fallback: str,
    ) -> dict[str, Any]:
        if not _valid_rule_type(rule_type) or not _valid_id(rule_id):
            return {"ok": False, "error": "操作无效"}
        try:
            result = operation(rule_type, rule_id)
            if result.get("ok") is True:
                return {"ok": True, payload_key: result.get(payload_key) or {}}
            return {"ok": False, "error": _message(result, messages, fallback)}
        except Exception:
            logger.exception("webview bridge rule history operation failed")
            return {"ok": False, "error": fallback}

    @staticmethod
    def _validate_batch_rules(rules) -> bool:
        return bool(
            isinstance(rules, list)
            and rules
            and all(
                isinstance(item, dict)
                and _valid_rule_type(item.get("rule_type"))
                and _valid_id(item.get("rule_id"))
                for item in rules
            )
        )

    def preview_project_rules_batch_impact(self, rules) -> dict[str, Any]:
        return self._batch_rule_operation(
            rules,
            rule_history_api.preview_project_rules_batch_impact,
            "impact",
            _PROJECT_RULE_BATCH_PREVIEW_MESSAGES,
            "批量预览失败",
        )

    def backfill_project_rules_batch(self, rules) -> dict[str, Any]:
        return self._batch_rule_operation(
            rules,
            rule_history_api.backfill_project_rules_batch,
            "result",
            _PROJECT_RULE_BATCH_APPLY_MESSAGES,
            "批量应用失败",
        )

    def set_project_rules_batch_enabled(self, rules, enabled) -> dict[str, Any]:
        if type(enabled) is not bool:
            return {"ok": False, "error": "操作无效"}
        return self._batch_rule_operation(
            rules,
            lambda values: rule_history_api.set_project_rules_batch_enabled(
                values,
                enabled,
            ),
            "result",
            _PROJECT_RULE_BATCH_TOGGLE_MESSAGES,
            "批量操作失败",
        )

    def _batch_rule_operation(
        self,
        rules,
        operation: Callable[[list[dict[str, Any]]], dict[str, Any]],
        payload_key: str,
        messages: dict[str, str],
        fallback: str,
    ) -> dict[str, Any]:
        if not self._validate_batch_rules(rules):
            return {"ok": False, "error": "操作无效"}
        try:
            result = operation(rules)
            if result.get("ok") is True:
                return {"ok": True, payload_key: result.get(payload_key) or {}}
            return {"ok": False, "error": _message(result, messages, fallback)}
        except Exception:
            logger.exception("webview bridge batch rule operation failed")
            return {"ok": False, "error": fallback}

    def automatic_rules_status(self) -> dict[str, Any]:
        try:
            result = rule_history_api.automatic_rules_status()
            if result.get("ok") is True:
                return {"ok": True, "status": result.get("status") or {}}
            return {"ok": False, "error": "加载自动规则状态失败"}
        except Exception:
            logger.exception("webview bridge automatic_rules_status failed")
            return {"ok": False, "error": "加载自动规则状态失败"}


__all__ = ["ProjectRulesBridgeMixin"]
