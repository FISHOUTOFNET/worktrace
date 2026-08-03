"""Sole owner of FD Work URLs, page knowledge, selectors and JS injection."""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path
import threading
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from .case_identity import normalize_case_label
from .contracts import FDWorkEntryDraft
from .limits import (
    FD_WORK_ADAPTER_CONTRACT_VERSION,
    FD_WORK_CASE_LABEL_MAX_LENGTH,
    FD_WORK_CASE_SEARCH_LIMIT,
)


class FDWorkPageType(Enum):
    LOGIN = "login"
    WORK_HOUR_LIST = "work_hour_list"
    UNAUTHORIZED = "unauthorized"
    ERROR = "error"
    UNKNOWN = "unknown"


class FDWorkPagePhase(Enum):
    LOGIN_CREDENTIALS = "login_credentials"
    LOGIN_CONFIRMATION = "login_confirmation"
    WORK_SHELL = "work_shell"
    WORK_INTERACTIVE = "work_interactive"
    UNAUTHORIZED = "unauthorized"
    ERROR = "error"
    UNKNOWN = "unknown"


_ACTION_ERRORS = frozenset(
    {
        "adapter_missing",
        "adapter_version_mismatch",
        "adapter_injection_failed",
        "case_input_missing",
        "case_input_not_interactive",
        "case_input_not_rendered",
        "case_aria_controls_missing",
        "case_popup_not_created",
        "case_popup_not_interactive",
        "case_query_not_applied",
        "case_results_stale",
        "case_results_timeout",
        "case_not_found",
        "case_ambiguous",
        "case_selection_mismatch",
        "duplicate_case_label",
        "ignored_required_field_missing",
        "lookup_superseded",
        "page_contract_changed",
        "page_operation_timeout",
    }
)


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

    def __init__(self, *, adapter_asset_path: str | Path | None = None) -> None:
        self._adapter_asset_path = (
            Path(adapter_asset_path)
            if adapter_asset_path is not None
            else Path(__file__).with_name("fd_work_adapter.js")
        )
        self._adapter_source: str | None = None
        self._source_lock = threading.Lock()

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
        return str(self._adapter_asset_path)

    @property
    def adapter_source(self) -> str:
        with self._source_lock:
            if self._adapter_source is None:
                self._adapter_source = self._adapter_asset_path.read_text(
                    encoding="utf-8"
                )
            return self._adapter_source

    def reload_adapter_source(self) -> str:
        """Explicit development helper; production keeps one instance cache."""
        with self._source_lock:
            self._adapter_source = self._adapter_asset_path.read_text(
                encoding="utf-8"
            )
            return self._adapter_source

    def detect_page(self, url: str | None) -> FDWorkPageType:
        hint = self.detect_page_hint(url)
        if hint in {"login_credentials", "login_confirmation"}:
            return FDWorkPageType.LOGIN
        if hint == "work_shell":
            return FDWorkPageType.WORK_HOUR_LIST
        if hint == "unauthorized":
            return FDWorkPageType.UNAUTHORIZED
        if hint == "error":
            return FDWorkPageType.ERROR
        return FDWorkPageType.UNKNOWN

    def detect_page_hint(self, url: str | None) -> str:
        parsed = urlparse(str(url or ""))
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.allowed_navigation_hosts
        ):
            return FDWorkPagePhase.UNKNOWN.value
        path = parsed.path.rstrip("/").lower() or "/"
        if path == "/login":
            return FDWorkPagePhase.LOGIN_CREDENTIALS.value
        if path == "/logintoken":
            return FDWorkPagePhase.LOGIN_CONFIRMATION.value
        if path == "/works/workhourlist":
            return FDWorkPagePhase.WORK_SHELL.value
        if path in {"/permission", "/unauthorized", "/forbidden"}:
            return FDWorkPagePhase.UNAUTHORIZED.value
        if path in {"/404", "/error", "/500"}:
            return FDWorkPagePhase.ERROR.value
        return FDWorkPagePhase.UNKNOWN.value

    def navigation_allowed(self, url: str | None) -> bool:
        parsed = urlparse(str(url or ""))
        return (
            parsed.scheme == "https"
            and parsed.hostname in self.allowed_navigation_hosts
        )

    @staticmethod
    def probe_page_phase(
        window: Any,
        callback: Callable[[Any], None],
    ) -> None:
        script = r"""
(function(){
  function visible(element) {
    if (!element) return false;
    var style = window.getComputedStyle ? window.getComputedStyle(element) : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    var rect = element.getBoundingClientRect ? element.getBoundingClientRect() : null;
    return !rect || (rect.width > 0 && rect.height > 0);
  }
  var path = String(window.location.pathname || "").replace(/\/$/, "").toLowerCase() || "/";
  var bodyReady = !!(document.body && document.body.firstElementChild);
  var form = document.querySelector('form#basic');
  var matter = document.querySelector('#basic_caseId[role="combobox"]');
  if (form && matter) return {phase:"work_shell", body_exists:bodyReady, input_exists:true};
  if (path === "/login") {
    var account = Array.prototype.find.call(
      document.querySelectorAll('input:not([type="password"]):not([type="hidden"]):not([type="checkbox"])'),
      visible
    );
    var password = Array.prototype.find.call(document.querySelectorAll('input[type="password"]'), visible);
    var login = Array.prototype.find.call(document.querySelectorAll('button,input[type="submit"]'), visible);
    if (bodyReady || account || password || login) {
      return {phase:"login_credentials", body_exists:bodyReady, input_exists:!!(account && password)};
    }
  }
  if (path === "/logintoken") {
    var confirmationControl = Array.prototype.find.call(
      document.querySelectorAll('button,a[href],input[type="button"],input[type="submit"]'),
      visible
    );
    if (bodyReady || confirmationControl) {
      return {phase:"login_confirmation", body_exists:bodyReady, input_exists:false};
    }
  }
  if (["/permission","/unauthorized","/forbidden"].indexOf(path) >= 0) {
    return {phase:"unauthorized", body_exists:bodyReady};
  }
  if (["/404","/error","/500"].indexOf(path) >= 0) {
    return {phase:"error", body_exists:bodyReady};
  }
  return {phase:"unknown", body_exists:bodyReady, input_exists:!!matter};
})()
""".strip()
        callback(window.evaluate_js(script))

    def install_adapter(self, window: Any) -> dict[str, Any]:
        try:
            check = (
                "\n;(function(){var a=window.WorkTraceFDWorkAdapter;"
                f"return a&&a.version==={self.adapter_version}"
                f"?{{ok:true,version:{self.adapter_version}}}"
                ":{ok:false,error:'adapter_injection_failed'};})()"
            )
            value = window.evaluate_js(self.adapter_source + check)
        except Exception:
            return {"ok": False, "error": "adapter_injection_failed"}
        if isinstance(value, Mapping) and value.get("ok") is False:
            return {"ok": False, "error": "adapter_injection_failed"}
        return {"ok": True, "version": self.adapter_version}

    def build_interactive_script(self, timeout_seconds: float) -> str:
        contract = self._case_contract(timeout_seconds)
        return (
            "(function(){var a=window.WorkTraceFDWorkAdapter;"
            f"if(!a)return {{ok:false,error:'adapter_missing'}};"
            f"if(a.version!=={self.adapter_version})"
            "return {ok:false,error:'adapter_version_mismatch'};"
            f"return a.interactiveHandshake({contract});}})()"
        )

    def build_fill_script(
        self,
        draft: FDWorkEntryDraft,
        timeout_seconds: float = 15.0,
    ) -> str:
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
        contract = self._entry_contract(timeout_seconds)
        return (
            "(function(){var a=window.WorkTraceFDWorkAdapter;"
            "if(!a)return {ok:false,error:'adapter_missing'};"
            f"if(a.version!=={self.adapter_version})"
            "return {ok:false,error:'adapter_version_mismatch'};"
            f"return a.fillEntry({payload},{contract});}})()"
        )

    def build_search_script(
        self,
        query: str,
        timeout_seconds: float = 8.0,
    ) -> str:
        payload = json.dumps(str(query), ensure_ascii=True, separators=(",", ":"))
        contract = self._case_contract(timeout_seconds)
        return (
            "(function(){var a=window.WorkTraceFDWorkAdapter;"
            "if(!a)return {ok:false,error:'adapter_missing'};"
            f"if(a.version!=={self.adapter_version})"
            "return {ok:false,error:'adapter_version_mismatch'};"
            f"return a.searchCases({payload},{contract});}})()"
        )

    def check_work_interactive(
        self,
        window: Any,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        result = self._evaluate_action(
            window,
            self.build_interactive_script(timeout_seconds),
            timeout_seconds=timeout_seconds,
            timeout_error="case_input_not_interactive",
        )
        return self._validated_action_result(result)

    def fill_entry(
        self,
        window: Any,
        draft: FDWorkEntryDraft,
        *,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        result = self._evaluate_action(
            window,
            self.build_fill_script(draft, timeout_seconds),
            timeout_seconds=timeout_seconds,
            timeout_error="page_operation_timeout",
        )
        if not isinstance(result, Mapping):
            return {"ok": False, "error": "page_contract_changed"}
        if result.get("ok") is True and result.get("status") == "filled":
            return {"ok": True, "status": "filled"}
        return self._validated_action_result(result)

    def search_cases(
        self,
        window: Any,
        query: str,
        *,
        timeout_seconds: float = 8.0,
    ) -> dict[str, Any]:
        result = self._evaluate_action(
            window,
            self.build_search_script(query, timeout_seconds),
            timeout_seconds=timeout_seconds,
            timeout_error="case_results_timeout",
        )
        if not isinstance(result, Mapping):
            return {"ok": False, "error": "page_contract_changed"}
        if result.get("ok") is False:
            return self._validated_action_result(result)
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
            canonical = normalize_case_label(label)
            if not canonical or len(canonical) > FD_WORK_CASE_LABEL_MAX_LENGTH:
                return {"ok": False, "error": "page_contract_changed"}
            if canonical in seen:
                return {"ok": False, "error": "duplicate_case_label"}
            seen.add(canonical)
            normalized.append(canonical)
        return {"ok": True, "labels": normalized}

    def _case_contract(self, timeout_seconds: float) -> str:
        timeout_ms = max(1, int(float(timeout_seconds) * 1000))
        popup_ms = min(3000, timeout_ms)
        payload = {
            "version": self.adapter_version,
            "page_type": FDWorkPageType.WORK_HOUR_LIST.value,
            "field": self.field_contract["case_number"],
            "fields": {"case_number": self.field_contract["case_number"]},
            "empty_text": "暂无数据",
            "max_options": FD_WORK_CASE_SEARCH_LIMIT,
            "max_label_length": FD_WORK_CASE_LABEL_MAX_LENGTH,
            "popup_timeout_ms": popup_ms,
            "lookup_timeout_ms": timeout_ms,
            "stability_ms": 200,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    def _entry_contract(self, timeout_seconds: float) -> str:
        payload = json.loads(self._case_contract(timeout_seconds))
        payload.update(
            {
                "form_selector": "form#basic",
                "fields": self.field_contract,
                "ignored_fields": self.ignored_field_contract,
                "native_actions": ("提交", "保存", "关闭"),
            }
        )
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _validated_action_result(result: Any) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            return {"ok": False, "error": "page_contract_changed"}
        if result.get("ok") is True:
            return dict(result)
        error = result.get("error")
        if isinstance(error, str) and error in _ACTION_ERRORS:
            safe = {"ok": False, "error": error}
            for key in (
                "phase",
                "document_visibility",
                "viewport_available",
                "input_exists",
                "input_interactive",
                "popup_exists",
                "popup_interactive",
                "loading_observed",
                "result_count",
            ):
                if key in result:
                    safe[key] = result[key]
            return safe
        return {"ok": False, "error": "page_contract_changed"}

    @staticmethod
    def _evaluate_action(
        window: Any,
        script: str,
        *,
        timeout_seconds: float,
        timeout_error: str,
    ) -> Any:
        completed = threading.Event()
        callback_result: list[Any] = []

        def accept_result(value: Any) -> None:
            if completed.is_set():
                return
            callback_result.append(value)
            completed.set()

        try:
            window.evaluate_js(script, callback=accept_result)
        except Exception:
            return {"ok": False, "error": "page_contract_changed"}
        if not completed.wait(timeout=max(0.01, float(timeout_seconds))):
            completed.set()
            return {"ok": False, "error": timeout_error}
        return callback_result[0] if callback_result else None


__all__ = ["FDWorkPageAdapter", "FDWorkPagePhase", "FDWorkPageType"]
