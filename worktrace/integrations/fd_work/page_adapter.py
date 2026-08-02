"""Sole owner of FD Work URLs, page knowledge, selectors and JS injection."""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path
import threading
from typing import Any, Callable
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from .contracts import FDWorkEntryDraft
from .limits import (
    FD_WORK_ADAPTER_CONTRACT_VERSION,
    FD_WORK_CASE_LABEL_MAX_LENGTH,
    FD_WORK_CASE_SEARCH_LIMIT,
)
from .case_identity import normalize_case_label


class FDWorkPageType(Enum):
    LOGIN = "login"
    WORK_HOUR_LIST = "work_hour_list"
    UNAUTHORIZED = "unauthorized"
    ERROR = "error"
    UNKNOWN = "unknown"


class FDWorkPageAdapter:
    """Versioned, fail-closed knowledge of the observed FD Work web UI."""

    adapter_version = FD_WORK_ADAPTER_CONTRACT_VERSION
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
    def login_url(self) -> str:
        business = urlsplit(self.business_url)
        return_path = business.path + (
            f"?{business.query}" if business.query else ""
        )
        return urlunsplit(
            (
                business.scheme,
                business.netloc,
                "/Login",
                urlencode({"returnUrl": return_path}),
                "",
            )
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

    def build_search_script(self, query: str) -> str:
        payload = json.dumps(str(query), ensure_ascii=True, separators=(",", ":"))
        contract = json.dumps(
            {
                "version": self.adapter_version,
                "page_type": FDWorkPageType.WORK_HOUR_LIST.value,
                "field": self.field_contract["case_number"],
                "empty_text": "暂无数据",
                "max_options": FD_WORK_CASE_SEARCH_LIMIT,
                "max_label_length": FD_WORK_CASE_LABEL_MAX_LENGTH,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return (
            "(function(){"
            "var a=window.WorkTraceFDWorkAdapter;"
            f"if(!a||a.version!=={self.adapter_version})"
            "return {ok:false,error:'adapter_version_mismatch'};"
            f"return a.searchCases({payload},{contract});"
            "})()"
        )

    @staticmethod
    def check_login_page_ready(
        window: Any,
        callback: Callable[[Any], None],
    ) -> None:
        script = """
(function(){
  function visible(element) {
    if (!element) return false;
    var style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden") return false;
    var rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }
  var account = Array.prototype.find.call(
    document.querySelectorAll('input:not([type="password"]):not([type="hidden"]):not([type="checkbox"])'),
    function(input) {
      return visible(input);
    }
  );
  var password = Array.prototype.find.call(
    document.querySelectorAll('input[type="password"]'),
    visible
  );
  var login = Array.prototype.find.call(
    document.querySelectorAll('button,input[type="submit"]'),
    function(button) {
      var label = String(button.textContent || button.value || "")
        .replace(/\\s+/g, "");
      return visible(button) && label === "登录";
    }
  );
  return {ready: !!(account && password && login)};
})()
""".strip()
        callback(window.evaluate_js(script))

    @staticmethod
    def check_work_hour_page_ready(
        window: Any,
        callback: Callable[[Any], None],
    ) -> None:
        script = """
(function(){
  var form = document.querySelector('form#basic');
  var matter = document.querySelector('#basic_caseId[role="combobox"]');
  var account = document.querySelector(
    'input:not([type="password"]):not([type="hidden"]):not([type="checkbox"])'
  );
  var password = document.querySelector('input[type="password"]');
  var login = Array.prototype.find.call(
    document.querySelectorAll('button,input[type="submit"]'),
    function(button) {
      var label = String(button.textContent || button.value || "")
        .replace(/\\s+/g, "");
      return label === "登录";
    }
  );
  var path = String(window.location.pathname || "").toLowerCase();
  var loginNavigation = (
    window.location.protocol === "https:" &&
    window.location.hostname === "work.fangdalaw.com" &&
    (path === "/login" || path === "/logintoken")
  );
  return {
    ready: !!(form && matter),
    login_ready: !!(account && password && login),
    login_navigation: loginNavigation
  };
})()
""".strip()
        callback(window.evaluate_js(script))

    def fill_entry(self, window: Any, draft: FDWorkEntryDraft) -> dict[str, Any]:
        result = self._evaluate(window, self.build_fill_script(draft))
        if not isinstance(result, dict):
            return {"ok": False, "error": "page_contract_changed"}
        if result.get("ok") is True and result.get("status") == "filled":
            return {"ok": True, "status": "filled"}
        error = result.get("error")
        if result.get("ok") is False and error in {
            "case_ambiguous",
            "case_not_found",
            "case_search_timeout",
            "case_selection_mismatch",
            "ignored_required_field_missing",
            "page_contract_changed",
        }:
            return {"ok": False, "error": error}
        return {"ok": False, "error": "page_contract_changed"}

    def search_cases(self, window: Any, query: str) -> dict[str, Any]:
        result = self._evaluate(
            window,
            self.build_search_script(query),
            timeout_error="case_search_timeout",
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "page_contract_changed"}
        if result.get("ok") is False:
            error = result.get("error")
            if isinstance(error, str) and error in {
                "adapter_version_mismatch",
                "case_not_found",
                "case_search_timeout",
                "lookup_superseded",
                "duplicate_case_label",
                "page_contract_changed",
            }:
                return {"ok": False, "error": error}
            return {"ok": False, "error": "page_contract_changed"}
        labels = result.get("labels")
        if result.get("ok") is not True or not isinstance(labels, list):
            return {"ok": False, "error": "page_contract_changed"}
        if len(labels) > FD_WORK_CASE_SEARCH_LIMIT:
            return {"ok": False, "error": "page_contract_changed"}
        normalized: list[str] = []
        seen: set[str] = set()
        for label in labels:
            if not isinstance(label, str):
                return {"ok": False, "error": "page_contract_changed"}
            canonical = self._normalize_label(label)
            if not canonical or len(canonical) > FD_WORK_CASE_LABEL_MAX_LENGTH:
                return {"ok": False, "error": "page_contract_changed"}
            if canonical in seen:
                return {"ok": False, "error": "duplicate_case_label"}
            seen.add(canonical)
            normalized.append(canonical)
        return {"ok": True, "labels": normalized}

    @staticmethod
    def _normalize_label(label: str) -> str:
        return normalize_case_label(label)

    def _evaluate(
        self,
        window: Any,
        script: str,
        *,
        timeout_error: str = "page_operation_timeout",
    ) -> Any:
        source = Path(self.adapter_asset_path).read_text(encoding="utf-8")
        window.evaluate_js(source)
        completed = threading.Event()
        callback_result: list[Any] = []

        def accept_result(value: Any) -> None:
            callback_result.append(value)
            completed.set()

        window.evaluate_js(
            script,
            callback=accept_result,
        )
        if not completed.wait(timeout=15):
            return {"ok": False, "error": timeout_error}
        return callback_result[0] if callback_result else None


__all__ = ["FDWorkPageAdapter", "FDWorkPageType"]
