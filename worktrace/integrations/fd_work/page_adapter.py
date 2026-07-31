"""Sole owner of FD Work URLs, page knowledge, selectors and JS injection."""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import urlparse

from .contracts import FDWorkEntryDraft


class FDWorkPageType(Enum):
    LOGIN = "login"
    WORK_HOUR_LIST = "work_hour_list"
    UNAUTHORIZED = "unauthorized"
    ERROR = "error"
    UNKNOWN = "unknown"


class FDWorkPageAdapter:
    """Versioned, fail-closed knowledge of the observed FD Work web UI."""

    adapter_version = 1
    business_url = "https://work.fangdalaw.com/Works/WorkHourList?picker=day"
    allowed_navigation_hosts = frozenset({"work.fangdalaw.com"})
    field_contract = {
        "case_number": {
            "selector": "#basic_caseId",
            "label": "案件",
            "listbox": "#basic_caseId_list",
        },
        "work_date": {
            "selector": 'form#basic input[placeholder="请选择日期"]',
            "label": "日期",
        },
        "duration_hours": {
            "selector": "#basic_hoursWorked",
            "label": "工时",
        },
        "narrative": {
            "selector": "#basic_narrative",
            "label": "工时描述",
        },
    }
    ignored_field_contract = (
        {"selector": "#basic_clientId", "label": "客户"},
        {"selector": "#basic_employeeId", "label": "计时人员"},
        {"selector": "#basic_nickName", "label": "暂代昵称"},
        {"selector": "#basic_writtenLanguage", "label": "书写语言"},
    )

    @property
    def adapter_asset_path(self) -> str:
        return str(Path(__file__).with_name("fd_work_adapter.js"))

    def detect_page(self, url: str | None) -> FDWorkPageType:
        parsed = urlparse(str(url or ""))
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_navigation_hosts:
            return FDWorkPageType.UNKNOWN
        path = parsed.path.rstrip("/").lower() or "/"
        if path in {"/login", "/logintoken"}:
            return FDWorkPageType.LOGIN
        if path == "/works/workhourlist":
            return FDWorkPageType.WORK_HOUR_LIST
        if path in {"/permission", "/unauthorized", "/forbidden"}:
            return FDWorkPageType.UNAUTHORIZED
        if path in {"/404", "/error", "/500"}:
            return FDWorkPageType.ERROR
        return FDWorkPageType.UNKNOWN

    def navigation_allowed(self, url: str | None) -> bool:
        parsed = urlparse(str(url or ""))
        return (
            parsed.scheme == "https"
            and parsed.hostname in self.allowed_navigation_hosts
        )

    def build_fill_script(self, draft: FDWorkEntryDraft) -> str:
        payload = json.dumps(
            {
                "work_date": draft.work_date,
                "case_number": draft.case_number,
                "duration_hours": draft.duration_hours,
                "narrative": draft.narrative,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        contract = json.dumps(
            {
                "version": self.adapter_version,
                "form_selector": "form#basic",
                "fields": self.field_contract,
                "ignored_fields": self.ignored_field_contract,
                "native_actions": ("提交", "保存", "关闭"),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return (
            "(function(){"
            "var a=window.WorkTraceFDWorkAdapter;"
            f"if(!a||a.version!=={self.adapter_version})"
            "return {ok:false,error:'adapter_version_mismatch'};"
            f"return a.fillEntry({payload},{contract});"
            "})()"
        )

    def fill_entry(self, window: Any, draft: FDWorkEntryDraft) -> dict[str, Any]:
        source = Path(self.adapter_asset_path).read_text(encoding="utf-8")
        window.evaluate_js(source)
        completed = threading.Event()
        callback_result: list[Any] = []

        def accept_result(value: Any) -> None:
            callback_result.append(value)
            completed.set()

        window.evaluate_js(
            self.build_fill_script(draft),
            callback=accept_result,
        )
        if not completed.wait(timeout=15):
            return {"ok": False, "error": "page_operation_timeout"}
        result = callback_result[0] if callback_result else None
        if not isinstance(result, dict):
            return {"ok": False, "error": "page_contract_changed"}
        return result


__all__ = ["FDWorkPageAdapter", "FDWorkPageType"]
