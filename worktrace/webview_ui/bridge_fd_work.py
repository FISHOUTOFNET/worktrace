"""Privacy-safe FD Work transport owned outside page-specific bridges."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..integrations.fd_work.limits import (
    FD_WORK_QUERY_MAX_LENGTH,
    FD_WORK_QUERY_MIN_LENGTH,
)

logger = logging.getLogger(__name__)
_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FD_WORK_MESSAGES = {
    "fd_work_disabled": "FD Work 插件已关闭，请在高级设置中开启",
    "renderer_unavailable": "无法使用 WebView2 打开 FD Work，请修复运行环境后重试",
    "session_start_failed": "连接 FD Work 失败",
    "login_required": "请先登录 FD Work",
    "fd_work_not_ready": "FD Work 尚未准备完成",
    "fd_work_busy": "FD Work 正在处理另一项操作",
    "case_search_timeout": "搜索 FD Work 案件超时",
    "case_not_found": "未找到匹配的 FD Work 案件",
    "case_ambiguous": "找到多个同名 FD Work 案件，无法安全选择",
    "duplicate_case_label": "FD Work 返回了无法区分的同名案件",
    "page_contract_changed": "FD Work 页面暂时不可用",
    "navigation_blocked": "FD Work 页面导航被安全策略阻止",
    "case_selection_required": "请从 FD Work 案件列表中选择",
    "case_selection_expired": "案件选择已过期，请重新搜索",
    "case_selection_mismatch": "案件名称与所选结果不一致，请重新选择",
    "window_unavailable": "FD Work 窗口不可用",
    "ignored_required_field_missing": "FD Work 仍有其他必填字段，请在完整页面中处理",
    "stale_selection": "当前时间段已变化，请重新选择",
    "in_progress_session": "进行中的时间段无法填入 FD Work",
    "uncategorized_project": "当前时间段属于未归类项目",
    "system_project": "当前时间段不属于具体用户项目",
    "project_unavailable": "当前项目已不可用",
    "empty_project_name": "项目名称为空，无法填入",
    "empty_narrative": "描述为空，无法填入",
    "invalid_duration": "工时必须大于零",
    "duration_exceeds_limit": "工时超过 FD Work 允许的范围",
}


def fd_work_message(code: object, fallback: str = "FD Work 操作失败") -> str:
    return FD_WORK_MESSAGES.get(str(code or ""), fallback)


class FDWorkBridgeMixin:
    """Exact shipping methods for the shared FD Work capability."""

    def get_fd_work_status(self) -> dict[str, Any]:
        try:
            return {"ok": True, "status": self._services.fd_work.get_settings_status()}
        except Exception:
            logger.exception("webview bridge get_fd_work_status failed")
            return {"ok": False, "error": "window_unavailable", "message": fd_work_message("window_unavailable")}

    def search_fd_work_cases(self, query, request_id) -> dict[str, Any]:
        if (
            type(query) is not str
            or not FD_WORK_QUERY_MIN_LENGTH <= len(query.strip()) <= FD_WORK_QUERY_MAX_LENGTH
            or type(request_id) is not str
            or not request_id
            or len(request_id) > 128
        ):
            return {"ok": False, "error": "invalid_input", "message": "案件搜索信息无效"}
        try:
            result = dict(self._services.fd_work.search_cases(query, request_id))
            if result.get("ok") is not True:
                result["message"] = fd_work_message(result.get("error"))
            return result
        except Exception:
            logger.exception("webview bridge search_fd_work_cases failed")
            return {"ok": False, "error": "page_contract_changed", "message": fd_work_message("page_contract_changed")}

    def show_fd_work_login(self) -> dict[str, Any]:
        try:
            result = dict(self._services.fd_work.prepare_session(show_login_if_required=True))
            if result.get("ok") is not True:
                result["message"] = fd_work_message(result.get("error"))
            return result
        except Exception:
            logger.exception("webview bridge show_fd_work_login failed")
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
                result["message"] = fd_work_message(result.get("error"), "打开 FD Work 失败")
            return result
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "operation_failed")
            if code not in FD_WORK_MESSAGES:
                logger.exception("webview bridge open_fd_work_entry failed")
                code = "operation_failed"
            return {"ok": False, "error": code, "message": fd_work_message(code, "打开 FD Work 失败")}


__all__ = ["FDWorkBridgeMixin", "FD_WORK_MESSAGES", "fd_work_message"]
