"""Pure display-safe presentation for the Project Rules WebView."""

from __future__ import annotations

from typing import Any


# Chinese error-message maps: each translates a stable API error code into a user-facing
# message; unknown codes collapse to the operation-specific generic failure so internal details are never surfaced.

_PROJECT_RULE_WRITE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "规则不存在",
    "operation_failed": "更新规则状态失败",
}

_PROJECT_RULE_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "project_not_found": "项目不存在",
    "duplicate_rule": "关键词规则已存在",
    "operation_failed": "新增关键词规则失败",
}

# Maps keyword-delete codes. not_found covers both "id missing" and "id is a folder rule" —
# both report 关键词规则不存在 so the user never learns which table the id belonged to.
_PROJECT_RULE_DELETE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "关键词规则不存在",
    "operation_failed": "删除关键词规则失败",
}

# Maps keyword-update codes. not_found covers both "id missing" and "id is a folder rule" —
# both report 关键词规则不存在 so the user never learns which table the id belonged to.
_PROJECT_RULE_UPDATE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "关键词规则不存在",
    "duplicate_rule": "关键词规则已存在",
    "operation_failed": "保存关键词规则失败",
}

_PROJECT_RULE_FOLDER_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "project_not_found": "项目不存在或不可用",
    "operation_failed": "新增文件夹规则失败",
}

# Maps folder-update codes. not_found covers both "id missing" and "id is a keyword rule" —
# both report 文件夹规则不存在 so the user never learns which table the id belonged to.
_PROJECT_RULE_FOLDER_UPDATE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "文件夹规则不存在",
    "operation_failed": "保存文件夹规则失败",
}

# Maps folder-delete codes. not_found covers both "id missing" and "id is a keyword rule" —
# both report 文件夹规则不存在 so the user never learns which table the id belonged to.
_PROJECT_RULE_FOLDER_DELETE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "文件夹规则不存在",
    "operation_failed": "删除文件夹规则失败",
}

# Maps Project lifecycle codes (create/edit/toggle/archive). Each operation has its own
# fallback message so a create failure never echoes an update-focused message.
_PROJECT_LIFECYCLE_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "system_project": "不能使用系统保留名称",
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
    "system_catalog_unavailable": "系统项目不可用，请运行恢复",
    "operation_failed": "更新项目状态失败",
}

_PROJECT_LIFECYCLE_ARCHIVE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "项目不存在",
    "system_project": "系统项目不能修改",
    "operation_failed": "归档项目失败",
}

_PROJECT_LIFECYCLE_DELETE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "项目不存在",
    "system_project": "系统项目不能删除",
    "operation_failed": "删除项目失败",
}

# Maps impact-preview codes. not_found covers both "id missing" and "id belongs to the other
# rule table" — both report 规则不存在 so the user never learns which table the id belonged to.
_PROJECT_RULE_IMPACT_PREVIEW_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "规则不存在",
    "operation_failed": "预览规则影响失败",
}

_PROJECT_RULE_BACKFILL_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "规则不存在",
    "rule_disabled": "规则未启用，无法应用",
    "project_not_available": "目标项目不可用",
    "too_many_matches": "命中记录过多，请先缩小范围",
    "operation_failed": "应用规则失败",
}

_PROJECT_RULE_BATCH_PREVIEW_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "规则不存在",
    "too_many_rules": "选择的规则过多",
    "operation_failed": "批量预览失败",
}

# Maps batch-apply codes. rule_disabled and project_not_available use "存在...规则" wording
# because the batch is all-or-nothing: a single disabled rule or unavailable target project
# blocks the whole batch.
_PROJECT_RULE_BATCH_APPLY_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "规则不存在",
    "too_many_rules": "选择的规则过多",
    "rule_disabled": "存在未启用规则，无法应用",
    "project_not_available": "存在目标项目不可用的规则",
    "too_many_matches": "命中记录过多，请先缩小范围",
    "operation_failed": "批量应用失败",
}

# Maps batch enable/disable codes. Toggle does not touch activities, so rule_disabled /
# project_not_available / too_many_matches cannot occur on this path.
_PROJECT_RULE_BATCH_TOGGLE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "规则不存在",
    "too_many_rules": "选择的规则过多",
    "operation_failed": "批量操作失败",
}

# Maps excluded keyword-create codes. The excluded project is system/special, so
# project_not_found cannot occur (the facade resolves it internally).
_EXCLUDED_KEYWORD_RULE_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "duplicate_rule": "关键词规则已存在",
    "system_catalog_unavailable": "系统项目不可用，请运行恢复",
    "operation_failed": "新增排除关键词规则失败",
}

_EXCLUDED_FOLDER_RULE_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "system_catalog_unavailable": "系统项目不可用，请运行恢复",
    "operation_failed": "新增排除文件夹规则失败",
}


# Payload helpers.


def _project_rules_project_payload(project: dict[str, Any]) -> dict[str, Any]:
    """Build one Project Rules display payload.

    The raw ``created_by`` value is not surfaced to the frontend; only
    display-safe boolean flags (``is_system`` / ``editable`` /
    ``can_toggle`` / ``can_archive`` / ``is_excluded``) are exposed for
    frontend decision logic.
    """
    project = _project_rules_mapping(project)
    project_name = _project_rules_text(project.get("name"), "未知项目")
    project_enabled = _project_rules_bool(project.get("enabled"), default=True)
    is_excluded = _project_rules_bool(project.get("is_excluded"), default=False)
    is_system = _project_rules_bool(project.get("is_system"), default=False)
    editable = _project_rules_bool(project.get("editable"), default=False)
    can_toggle = _project_rules_bool(project.get("can_toggle"), default=False)
    can_archive = _project_rules_bool(project.get("can_archive"), default=False)
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
        "language": _project_rules_text(project.get("language"), "中文"),
        "last_used_at": _project_rules_optional_text(project.get("last_used_at")),
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
    """Build the narrow project summary payload for lifecycle writes.

    Only exposes display-safe fields (``id`` / ``name`` / ``description`` /
    ``language`` / ``enabled`` / ``archived``). Never surfaces
    ``created_by`` / ``created_at`` / ``updated_at`` / raw row / traceback /
    SQL.
    """
    project = _project_rules_mapping(project)
    return {
        "id": _project_rules_int(project.get("id")),
        "name": _project_rules_text(project.get("name"), ""),
        "description": _project_rules_text(project.get("description"), ""),
        "language": _project_rules_text(project.get("language"), "中文"),
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
        "detail": f"{scope} | {state}",
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
        "detail": state,
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


def _project_rules_optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
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

__all__ = [
    "_EXCLUDED_FOLDER_RULE_CREATE_MESSAGES",
    "_EXCLUDED_KEYWORD_RULE_CREATE_MESSAGES",
    "_PROJECT_LIFECYCLE_ARCHIVE_MESSAGES",
    "_PROJECT_LIFECYCLE_CREATE_MESSAGES",
    "_PROJECT_LIFECYCLE_DELETE_MESSAGES",
    "_PROJECT_LIFECYCLE_TOGGLE_MESSAGES",
    "_PROJECT_LIFECYCLE_UPDATE_MESSAGES",
    "_PROJECT_RULE_BACKFILL_MESSAGES",
    "_PROJECT_RULE_BATCH_APPLY_MESSAGES",
    "_PROJECT_RULE_BATCH_PREVIEW_MESSAGES",
    "_PROJECT_RULE_BATCH_TOGGLE_MESSAGES",
    "_PROJECT_RULE_CREATE_MESSAGES",
    "_PROJECT_RULE_DELETE_MESSAGES",
    "_PROJECT_RULE_FOLDER_CREATE_MESSAGES",
    "_PROJECT_RULE_FOLDER_DELETE_MESSAGES",
    "_PROJECT_RULE_FOLDER_UPDATE_MESSAGES",
    "_PROJECT_RULE_IMPACT_PREVIEW_MESSAGES",
    "_PROJECT_RULE_UPDATE_MESSAGES",
    "_PROJECT_RULE_WRITE_MESSAGES",
    "_project_lifecycle_summary",
    "_project_rules_project_payload",
]
