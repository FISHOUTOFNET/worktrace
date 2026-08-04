"""Sole owner of FD Work URLs, page phases, selectors, and adapter actions."""

from __future__ import annotations

from enum import Enum
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from .case_identity import normalize_case_label
from .contracts import FDWorkEntryDraft
from .limits import FD_WORK_ADAPTER_CONTRACT_VERSION, FD_WORK_CASE_LABEL_MAX_LENGTH
from .window_executor import FDWorkWindowCommandResult


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
        "case_popup_not_created",
        "case_not_found",
        "case_ambiguous",
        "case_selection_required",
        "case_selection_mismatch",
        "ignored_required_field_missing",
        "fd_work_busy",
        "lookup_superseded",
        "page_contract_changed",
        "page_operation_timeout",
        "callback_timeout",
        "dom_contract_changed",
        "executor_rejected",
        "guard_rejected",
        "javascript_exception",
        "navigation_changed",
        "non_mapping_result",
        "window_closed",
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
    def __init__(
        self,
        *,
        adapter_asset_path: str | Path | None = None,
        diagnostic_callback: Callable[[Mapping[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._adapter_asset_path = (
            Path(adapter_asset_path)
            if adapter_asset_path is not None
            else Path(__file__).with_name("fd_work_adapter.js")
        )
        self._adapter_source: str | None = None
        self._source_lock = threading.Lock()
        self._diagnostic_callback = diagnostic_callback or self._log_action_diagnostic
        self._clock = clock

    @property
    def login_url(self) -> str:
        business = urlsplit(self.business_url)
        return_path = business.path + (f"?{business.query}" if business.query else "")
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
                self._adapter_source = self._adapter_asset_path.read_text(encoding="utf-8")
            return self._adapter_source

    def reload_adapter_source(self) -> str:
        with self._source_lock:
            self._adapter_source = self._adapter_asset_path.read_text(encoding="utf-8")
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
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_navigation_hosts:
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
        return parsed.scheme == "https" and parsed.hostname in self.allowed_navigation_hosts

    @staticmethod
    def probe_page_phase(window: Any, callback: Callable[[Any], None]) -> None:
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
  var matter = document.querySelector('#basic_caseId');
  var wrapper = matter && typeof matter.closest === "function"
    ? matter.closest('.ant-select[name="workhours/matter/selector"]') : null;
  var formOwnsMatter = !!(form && matter && form.contains(matter));
  var roleMatches = !!(matter && String(matter.getAttribute("role") || "").toLowerCase() === "combobox");
  var shellFacts = {
    body_exists: bodyReady,
    input_exists: !!matter,
    form_exists: !!form,
    wrapper_exists: !!wrapper,
    role_matches: roleMatches
  };
  if (formOwnsMatter && wrapper) return Object.assign({phase:"work_shell"}, shellFacts);
  if (path === "/login") {
    var account = Array.prototype.find.call(
      document.querySelectorAll('input:not([type="password"]):not([type="hidden"]):not([type="checkbox"])'),
      visible
    );
    var password = Array.prototype.find.call(document.querySelectorAll('input[type="password"]'), visible);
    if (bodyReady || account || password) {
      return {phase:"login_credentials", body_exists:bodyReady, input_exists:!!(account && password)};
    }
  }
  if (path === "/logintoken") {
    if (bodyReady) return {phase:"login_confirmation", body_exists:true, input_exists:false};
  }
  if (["/permission","/unauthorized","/forbidden"].indexOf(path) >= 0) {
    return {phase:"unauthorized", body_exists:bodyReady};
  }
  if (["/404","/error","/500"].indexOf(path) >= 0) {
    return {phase:"error", body_exists:bodyReady};
  }
  return Object.assign({phase:"unknown"}, shellFacts);
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

    def await_stable_work_shell(
        self,
        window: Any,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._run_action(
            window,
            "awaitStableWorkShell",
            self._picker_contract(contract),
            respect_operation_deadline=True,
        )

    def enter_case_picker(
        self,
        window: Any,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._run_action(
            window,
            "enterCasePicker",
            self._picker_contract(contract),
        )

    def read_selected_case(
        self,
        window: Any,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        result_value = self._run_action(
            window,
            "readSelectedCase",
            self._picker_contract(contract),
        )
        if result_value.get("ok") is not True:
            return result_value
        label = result_value.get("label")
        if not isinstance(label, str):
            return {"ok": False, "error": "dom_contract_changed"}
        canonical = normalize_case_label(label)
        if not canonical or len(canonical) > FD_WORK_CASE_LABEL_MAX_LENGTH:
            return {"ok": False, "error": "dom_contract_changed"}
        return {"ok": True, "label": canonical}

    def leave_case_picker(
        self,
        window: Any,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._run_action(
            window,
            "leaveCasePicker",
            self._picker_contract(contract),
            takes_contract=False,
        )

    def fill_entry(
        self,
        window: Any,
        draft: FDWorkEntryDraft,
        *,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "work_date": draft.work_date,
            "case_number": draft.case_number,
            "duration_hours": draft.duration_hours,
            "narrative": draft.narrative,
        }
        result_value = self._run_action(
            window,
            "fillEntry",
            self._entry_contract(contract),
            payload=payload,
            respect_operation_deadline=True,
        )
        if result_value.get("ok") is True and result_value.get("status") == "filled":
            return {"ok": True, "status": "filled"}
        return result_value

    def _picker_contract(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        timeout_seconds = max(0.01, float(operation.get("timeout_seconds") or 5.0))
        operation_deadline_ms = int(
            operation.get("operation_deadline_ms")
            or (time.time() * 1000 + timeout_seconds * 1000)
        )
        return {
            "version": self.adapter_version,
            "page_type": FDWorkPageType.WORK_HOUR_LIST.value,
            "operation_nonce": str(operation.get("operation_nonce") or ""),
            "operation_generation": int(operation.get("operation_generation") or 0),
            "navigation_generation": int(operation.get("navigation_generation") or 0),
            "deadline_ms": max(1, int(timeout_seconds * 1000)),
            "operation_deadline_ms": operation_deadline_ms,
            "form_selector": "form#basic",
            "field": self.field_contract["case_number"],
            "fields": {"case_number": self.field_contract["case_number"]},
            "max_label_length": FD_WORK_CASE_LABEL_MAX_LENGTH,
        }

    def _entry_contract(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._picker_contract(operation)
        payload.update(
            {
                "fields": self.field_contract,
                "native_actions": ("提交", "保存", "关闭"),
            }
        )
        return payload

    def _run_action(
        self,
        window: Any,
        action: str,
        contract: Mapping[str, Any],
        *,
        payload: Mapping[str, Any] | None = None,
        takes_contract: bool = True,
        respect_operation_deadline: bool = False,
    ) -> dict[str, Any]:
        contract_json = json.dumps(dict(contract), ensure_ascii=True, separators=(",", ":"))
        if payload is not None:
            payload_json = json.dumps(dict(payload), ensure_ascii=True, separators=(",", ":"))
            arguments = f"{payload_json},{contract_json}"
        elif takes_contract:
            arguments = contract_json
        else:
            arguments = ""
        script = (
            "(function(){var a=window.WorkTraceFDWorkAdapter;"
            "if(!a)return {ok:false,error:'adapter_missing'};"
            f"if(a.version!=={self.adapter_version})"
            "return {ok:false,error:'adapter_version_mismatch'};"
            f"if(typeof a.{action}!==\"function\")"
            "return {ok:false,error:'adapter_version_mismatch'};"
            f"return a.{action}({arguments});}})()"
        )
        remaining_ms = float(contract.get("deadline_ms") or 5000)
        absolute_deadline = contract.get("operation_deadline_ms")
        if respect_operation_deadline and isinstance(absolute_deadline, (int, float)):
            remaining_ms = min(
                remaining_ms,
                max(10.0, float(absolute_deadline) - time.time() * 1000),
            )
        timeout_seconds = max(0.01, remaining_ms / 1000)
        started_at = self._clock()
        value, internal_error_kind, callback_executed, result_type = self._evaluate_action(
            window,
            script,
            timeout_seconds=timeout_seconds,
        )
        if internal_error_kind is None:
            if not isinstance(value, Mapping):
                internal_error_kind = "non_mapping_result"
            elif value.get("ok") is not True:
                returned_error = value.get("error")
                internal_error_kind = (
                    returned_error
                    if isinstance(returned_error, str) and returned_error in _ACTION_ERRORS
                    else "dom_contract_changed"
                )
        self._emit_action_diagnostic(
            action=action,
            contract=contract,
            value=value,
            internal_error_kind=internal_error_kind,
            callback_executed=callback_executed,
            result_type=result_type,
            elapsed_ms=max(0, int((self._clock() - started_at) * 1000)),
        )
        return self._validated_action_result(value, internal_error_kind)

    @staticmethod
    def _validated_action_result(
        value: Any,
        internal_error_kind: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {"ok": False, "error": internal_error_kind or "non_mapping_result"}
        if value.get("ok") is True:
            return dict(value)
        error = value.get("error")
        if isinstance(error, str) and error in _ACTION_ERRORS:
            safe: dict[str, Any] = {"ok": False, "error": error}
            for key in (
                "status",
                "label",
                "document_visibility",
                "viewport_available",
                "input_exists",
                "input_interactive",
            ):
                if key in value:
                    safe[key] = value[key]
            return safe
        return {"ok": False, "error": internal_error_kind or "dom_contract_changed"}

    @staticmethod
    def _evaluate_action(
        window: Any,
        script: str,
        *,
        timeout_seconds: float,
    ) -> tuple[Any, str | None, bool, str]:
        completed = threading.Event()
        callback_result: list[Any] = []
        callback_executed = False

        execute_window_js = getattr(window, "execute_window_js", None)
        if callable(execute_window_js):
            execution = execute_window_js(script, timeout=timeout_seconds)
            if not isinstance(execution, FDWorkWindowCommandResult):
                return None, "non_mapping_result", False, "none"
            if execution.ok is not True:
                error_kind = execution.error_kind or "executor_rejected"
                if error_kind == "command_exception":
                    error_kind = "javascript_exception"
                return (
                    {"ok": False, "error": error_kind},
                    error_kind,
                    execution.callback_executed,
                    "none",
                )
            value = execution.value
            return (
                value,
                None,
                execution.callback_executed,
                type(value).__name__ if value is not None else "none",
            )

        def accept_result(value: Any) -> None:
            nonlocal callback_executed
            if completed.is_set():
                return
            callback_executed = True
            callback_result.append(value)
            completed.set()

        try:
            window.evaluate_js(script, callback=accept_result)
        except TypeError:
            try:
                value = window.evaluate_js(script)
                return value, None, False, type(value).__name__ if value is not None else "none"
            except Exception:
                return (
                    {"ok": False, "error": "javascript_exception"},
                    "javascript_exception",
                    False,
                    "none",
                )
        except Exception:
            return (
                {"ok": False, "error": "javascript_exception"},
                "javascript_exception",
                False,
                "none",
            )
        if not completed.wait(timeout=max(0.01, float(timeout_seconds))):
            completed.set()
            return (
                {"ok": False, "error": "callback_timeout"},
                "callback_timeout",
                False,
                "none",
            )
        value = callback_result[0] if callback_result else None
        return (
            value,
            None,
            callback_executed,
            type(value).__name__ if value is not None else "none",
        )

    def _emit_action_diagnostic(
        self,
        *,
        action: str,
        contract: Mapping[str, Any],
        value: Any,
        internal_error_kind: str | None,
        callback_executed: bool,
        result_type: str,
        elapsed_ms: int,
    ) -> None:
        diagnostic: dict[str, Any] = {
            "action": action,
            "internal_error_kind": internal_error_kind or "none",
            "elapsed_ms": elapsed_ms,
            "adapter_version": self.adapter_version,
            "operation_generation": int(contract.get("operation_generation") or 0),
            "navigation_generation": int(contract.get("navigation_generation") or 0),
            "callback_executed": callback_executed,
            "result_type": result_type,
        }
        if isinstance(value, Mapping):
            for key in (
                "document_visibility",
                "viewport_available",
                "input_exists",
                "input_interactive",
                "form_exists",
                "wrapper_exists",
            ):
                if key in value and isinstance(value[key], (bool, str)):
                    diagnostic[key] = value[key]
        try:
            self._diagnostic_callback(diagnostic)
        except Exception:
            pass

    @staticmethod
    def _log_action_diagnostic(diagnostic: Mapping[str, Any]) -> None:
        logging.info(
            "fd_work_window_action %s",
            " ".join(f"{key}={value}" for key, value in diagnostic.items()),
        )


__all__ = ["FDWorkPageAdapter", "FDWorkPagePhase", "FDWorkPageType"]
