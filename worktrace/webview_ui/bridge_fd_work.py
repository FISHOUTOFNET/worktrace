"""Privacy-safe FD Work transport owned outside page-specific bridges."""

from __future__ import annotations

import logging
import re
from typing import Any

from worktrace.integrations.fd_work.error_codes import public_fd_work_error


logger = logging.getLogger(__name__)
_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FD_WORK_MESSAGES = {
    "fd_work_disabled": "FD Work 插件已关闭，请在高级设置中开启",
    "deferred_by_privacy": "请先确认隐私说明",
    "renderer_unavailable": "无法使用 WebView2 打开 FD Work，请修复运行环境后重试",
    "session_starting": "FD Work 窗口正在创建，请稍后重试",
    "session_start_timeout": "连接 FD Work 超时，请检查网络或重新连接",
    "session_probe_inconclusive": "登录状态尚未确认，请登录或重试",
    "work_shell_timeout": "FD Work 工时页面加载超时",
    "session_start_failed": "连接 FD Work 失败",
    "login_required": "请先登录 FD Work",
    "fd_work_not_ready": "FD Work 尚未准备完成",
    "fd_work_busy": "FD Work 正在处理另一项操作",
    "lookup_superseded": "案件搜索已被更新的查询替代",
    "case_search_timeout": "搜索 FD Work 案件超时",
    "case_input_missing": "未找到 FD Work 案件输入框",
    "case_input_not_interactive": "FD Work 案件控件尚未准备完成",
    "case_input_not_rendered": "FD Work 案件控件尚未显示",
    "work_page_not_ready": "FD Work 工时页面尚未准备完成",
    "entry_create_action_missing": "未找到 FD Work 创建工时按钮",
    "entry_create_action_ambiguous": "找到多个创建工时按钮，无法安全继续",
    "entry_create_action_disabled": "FD Work 创建工时按钮当前不可用",
    "entry_editor_not_rendered": "FD Work 工时编辑器未能打开",
    "case_aria_controls_missing": "FD Work 案件页面结构发生变化",
    "case_popup_not_created": "FD Work 案件下拉框未能打开",
    "case_popup_not_interactive": "FD Work 案件下拉框尚未准备完成",
    "case_query_not_applied": "FD Work 未接受当前搜索内容",
    "case_results_stale": "FD Work 案件结果尚未刷新",
    "case_results_timeout": "FD Work 案件搜索超时",
    "case_not_found": "已关联的 FD Work 案件当前不可用，请在项目规则中重新关联。",
    "case_ambiguous": "找到多个同名 FD Work 案件，无法安全选择",
    "duplicate_case_label": "FD Work 返回了无法区分的同名案件",
    "page_contract_changed": "FD Work 页面暂时不可用",
    "adapter_missing": "FD Work 页面适配器尚未安装",
    "adapter_version_mismatch": "FD Work 页面适配器版本不匹配",
    "adapter_injection_failed": "FD Work 页面适配器安装失败",
    "navigation_blocked": "FD Work 页面导航被安全策略阻止",
    "case_selection_required": "请从 FD Work 案件列表中选择",
    "case_selection_expired": "案件选择已过期，请重新搜索",
    "case_selection_mismatch": "案件名称与所选结果不一致，请重新选择",
    "picker_canceled": "案件选择已取消",
    "picker_superseded": "案件选择已失效，请重新打开",
    "window_unavailable": "FD Work 窗口不可用",
    "ignored_required_field_missing": "FD Work 仍有其他必填字段，请在完整页面中处理",
    "stale_selection": "当前时间段已变化，请重新选择",
    "in_progress_session": "进行中的时间段无法填入 FD Work",
    "uncategorized_project": "当前时间段属于未归类项目",
    "system_project": "当前时间段不属于具体用户项目",
    "project_unavailable": "当前项目已不可用",
    "project_not_fd_work_bound": "当前项目未关联 FD Work 案件，请在“项目规则”中编辑项目并从 FD Work 案件列表中选择。",
    "empty_project_name": "项目名称为空，无法填入",
    "empty_narrative": "描述为空，无法填入",
    "invalid_duration": "工时必须大于零",
    "duration_exceeds_limit": "工时超过 FD Work 允许的范围",
    "save_outcome_unknown": "FD Work 已执行保存，但结果未确认，请先在 FD Work 页面确认是否已保存，确认前不要重复填入",
    "fd_work_page_unavailable": "FD Work 页面暂时不可用",
    "fd_work_operation_timeout": "FD Work 操作超时，请重试",
    "fd_work_window_unavailable": "FD Work 窗口不可用，请检查 WebView2 运行环境",
    "fd_work_persistence_unconfirmed": "项目写入结果无法确认，请刷新后检查",
    "fd_work_inconsistent_state": "项目与 FD Work 关联状态不一致，请刷新后检查",
}


def fd_work_message(code: object, fallback: str = "FD Work 操作失败") -> str:
    return FD_WORK_MESSAGES.get(str(code or ""), fallback)


class FDWorkBridgeMixin:
    """Exact shipping methods for the shared FD Work capability."""

    def get_fd_work_status(self) -> dict[str, Any]:
        try:
            return {"ok": True, "status": self._services.fd_work.get_settings_status()}
        except Exception:
            logger.error("fd_work_bridge_failed action=get_status internal_error_kind=python_exception")
            code = "fd_work_window_unavailable"
            return {"ok": False, "error": code, "message": fd_work_message(code)}

    def open_fd_work_case_picker(self, request_id, action="open") -> dict[str, Any]:
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            return {"ok": False, "error": "invalid_input", "message": "案件选择请求无效"}
        if action not in {"open", "cancel"}:
            return {"ok": False, "error": "invalid_input", "message": "案件选择请求无效"}
        if action == "cancel":
            return self.cancel_fd_work_case_picker(request_id)
        try:
            result = dict(self._services.fd_work.open_case_picker(request_id))
            if result.get("ok") is not True:
                result["error"] = public_fd_work_error(result.get("error"))
                result["message"] = fd_work_message(result["error"])
            return result
        except Exception:
            logger.error("fd_work_bridge_failed action=open_picker internal_error_kind=python_exception")
            code = "fd_work_window_unavailable"
            return {"ok": False, "error": code, "message": fd_work_message(code)}

    def cancel_fd_work_case_picker(self, request_id) -> dict[str, Any]:
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            return {"ok": False, "error": "invalid_input", "message": "案件选择请求无效"}
        try:
            result = dict(self._services.fd_work.cancel_case_picker(request_id))
            if result.get("ok") is not True:
                result["error"] = public_fd_work_error(result.get("error"))
                result["message"] = fd_work_message(result["error"])
            return result
        except Exception:
            logger.error("fd_work_bridge_failed action=cancel_picker internal_error_kind=python_exception")
            code = "fd_work_window_unavailable"
            return {"ok": False, "error": code, "message": fd_work_message(code)}

    def show_fd_work_login(self) -> dict[str, Any]:
        try:
            result = dict(self._services.fd_work.prepare_session(show_login_if_required=True))
            if result.get("ok") is not True:
                result["error"] = public_fd_work_error(result.get("error"))
                result["message"] = fd_work_message(result["error"])
            return result
        except Exception:
            logger.error("fd_work_bridge_failed action=show_login internal_error_kind=python_exception")
            return {"ok": False, "error": "session_start_failed", "message": fd_work_message("session_start_failed")}

    def open_fd_work_entry(self, report_date, projection_instance_key, expected_projection_revision) -> dict[str, Any]:
        values = (projection_instance_key, expected_projection_revision)
        if (
            type(report_date) is not str
            or not _DATE_SHAPE_RE.match(report_date)
            or any(type(value) is not str or not value.strip() for value in values)
        ):
            return {"ok": False, "error": "invalid_input", "message": "当前时间段信息无效"}
        try:
            result = dict(self._services.fd_work.open_entry(
                report_date,
                projection_instance_key.strip(),
                expected_projection_revision.strip(),
            ))
            if result.get("ok") is not True:
                result["error"] = public_fd_work_error(result.get("error"))
                result["message"] = fd_work_message(result["error"], "打开 FD Work 失败")
            return result
        except Exception as exc:
            code = public_fd_work_error(getattr(exc, "code", "") or "operation_failed")
            if code not in FD_WORK_MESSAGES:
                logger.error("fd_work_bridge_failed action=open_entry internal_error_kind=python_exception")
                code = "operation_failed"
            return {"ok": False, "error": code, "message": fd_work_message(code, "打开 FD Work 失败")}


__all__ = ["FDWorkBridgeMixin", "FD_WORK_MESSAGES", "fd_work_message"]
