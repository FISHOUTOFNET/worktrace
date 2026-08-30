"""Public FD Work page adapter with a separately injected human picker session."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any, Mapping

from ._page_adapter_core import (
    FDWorkPageAdapter as _CoreFDWorkPageAdapter,
    FDWorkPagePhase,
    FDWorkPageType,
    _WORK_SHELL_WINDOW_RESOLVER,
)


_VERIFIED_WORK_SHELL_WINDOW_RESOLVER = r"""
function workTraceVerifiedWorkShellCandidates() {
  var windows = [window];
  var cursor = 0;
  while (cursor < windows.length && windows.length < 16) {
    var owner = windows[cursor++];
    try {
      var frames = owner.document.querySelectorAll("iframe");
      Array.prototype.forEach.call(frames, function(frame) {
        if (windows.length >= 16) return;
        try {
          var child = frame.contentWindow;
          if (child && windows.indexOf(child) < 0) windows.push(child);
        } catch (_error) {}
      });
    } catch (_error) {}
  }
  var candidates = [];
  for (var index = 0; index < windows.length; index += 1) {
    try {
      var candidate = windows[index];
      var path = String(candidate.location.pathname || "")
        .replace(/\/$/, "").toLowerCase() || "/";
      var rootReady = !!(candidate.document.documentElement && candidate.document.body);
      var loginMarker = !!candidate.document.querySelector(".loginPage");
      var shellMarker = !!candidate.document.querySelector(
        ".workHourList, input[placeholder='请选择日期']"
      );
      if (path === "/works/workhourlist" && rootReady && !loginMarker && shellMarker) {
        candidates.push(candidate);
      }
    } catch (_error) {}
  }
  return candidates;
}
function workTraceWorkShellWindow() {
  var candidates = workTraceVerifiedWorkShellCandidates();
  return candidates.length === 1 ? candidates[0] : null;
}
""".strip()


def _with_verified_work_shell_resolver(script: str) -> str:
    if _WORK_SHELL_WINDOW_RESOLVER not in script:
        raise ValueError("FD Work shell resolver missing from adapter script")
    return script.replace(
        _WORK_SHELL_WINDOW_RESOLVER,
        _VERIFIED_WORK_SHELL_WINDOW_RESOLVER,
        1,
    )


class _VerifiedResolverWindow:
    """Rewrite one core adapter script without adding another WebView round trip."""

    def __init__(self, window: Any) -> None:
        self._window = window

    def evaluate_js(self, script: str, *args: Any, **kwargs: Any) -> Any:
        return self._window.evaluate_js(
            _with_verified_work_shell_resolver(script),
            *args,
            **kwargs,
        )


class FDWorkPageAdapter(_CoreFDWorkPageAdapter):
    """Keep the stable automation adapter separate from the user-owned picker."""

    def __init__(self, *args: Any, picker_asset_path: str | Path | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._picker_asset_path = (
            Path(picker_asset_path)
            if picker_asset_path is not None
            else Path(__file__).with_name("fd_work_picker_session.js")
        )
        self._picker_source: str | None = None
        self._picker_source_lock = threading.Lock()

    @property
    def picker_asset_path(self) -> str:
        return str(self._picker_asset_path)

    @property
    def picker_source(self) -> str:
        with self._picker_source_lock:
            if self._picker_source is None:
                with self._picker_asset_path.open("r", encoding="utf-8") as handle:
                    self._picker_source = handle.read()
            return self._picker_source

    def reload_adapter_source(self) -> str:
        base_source = super().reload_adapter_source()
        with self._picker_source_lock:
            with self._picker_asset_path.open("r", encoding="utf-8") as handle:
                self._picker_source = handle.read()
        return base_source

    @staticmethod
    def probe_page_phase(window: Any, callback: Any) -> None:
        script = (
            "(function(){"
            f"{_VERIFIED_WORK_SHELL_WINDOW_RESOLVER}"
            r"""
  function visible(element) {
    if (!element) return false;
    var style = window.getComputedStyle ? window.getComputedStyle(element) : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    var rect = element.getBoundingClientRect ? element.getBoundingClientRect() : null;
    return !rect || (rect.width > 0 && rect.height > 0);
  }
  var path = String(window.location.pathname || "").replace(/\/$/, "").toLowerCase() || "/";
  var bodyReady = !!(document.body && document.body.firstElementChild);
  if (path === "/login") {
    var account = Array.prototype.find.call(
      document.querySelectorAll('input:not([type="password"]):not([type="hidden"]):not([type="checkbox"])'),
      visible
    );
    var password = Array.prototype.find.call(document.querySelectorAll('input[type="password"]'), visible);
    return {phase:"login_credentials", body_exists:bodyReady, input_exists:!!(account && password)};
  }
  if (path === "/logintoken") {
    return {phase:"login_confirmation", body_exists:bodyReady, input_exists:false};
  }
  if (["/permission","/unauthorized","/forbidden"].indexOf(path) >= 0) {
    return {phase:"unauthorized", body_exists:bodyReady};
  }
  if (["/404","/error","/500"].indexOf(path) >= 0) {
    return {phase:"error", body_exists:bodyReady};
  }
  var workCandidates = workTraceVerifiedWorkShellCandidates();
  var editorExists = false;
  if (workCandidates.length === 1) {
    try {
      var owner = workCandidates[0].document;
      var form = owner.querySelector("form[id='basic']");
      var matter = owner.querySelector("[id='basic_caseId']");
      editorExists = !!(form && matter && form.contains(matter));
    } catch (_error) {}
  }
  var shellFacts = {
    body_exists: bodyReady,
    work_page_candidate_count: workCandidates.length,
    editor_exists: editorExists,
    work_shell_verified: workCandidates.length === 1
  };
  if (workCandidates.length === 1) return Object.assign({phase:"work_shell"}, shellFacts);
  return Object.assign({phase:"unknown"}, shellFacts);
"""
            "})()"
        )
        callback(window.evaluate_js(script))

    def install_adapter(self, window: Any) -> dict[str, Any]:
        result = dict(super().install_adapter(_VerifiedResolverWindow(window)))
        if result.get("ok") is not True:
            return result
        picker = self._ensure_picker_session(window)
        if picker.get("ok") is not True:
            return {"ok": False, "error": "adapter_injection_failed"}
        return {"ok": True, "version": self.adapter_version}

    @staticmethod
    def _evaluate_action(
        window: Any,
        script: str,
        *,
        timeout_seconds: float,
    ) -> tuple[Any, str | None, bool, str]:
        try:
            hardened_script = _with_verified_work_shell_resolver(script)
        except ValueError:
            return (
                {"ok": False, "error": "page_contract_changed"},
                "page_contract_changed",
                False,
                "none",
            )
        return _CoreFDWorkPageAdapter._evaluate_action(
            window,
            hardened_script,
            timeout_seconds=timeout_seconds,
        )

    def reset_case_picker(
        self,
        window: Any,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Synchronously remove only WorkTrace-owned picker/fill artifacts."""
        script = (
            "(function(){"
            f"{_VERIFIED_WORK_SHELL_WINDOW_RESOLVER}"
            "/*\"action_nonce\":\"direct-picker-reset\",\"action\":\"leaveCasePicker\"*/"
            "var target=workTraceWorkShellWindow();"
            "if(!target)return {ok:false,error:'page_contract_changed'};"
            "var doc=target.document;"
            "var p=target.WorkTraceFDWorkPickerSession;"
            "var ownedBlocker=doc.getElementById('worktrace-fdwork-picker-blocker');"
            "var restoreInput=!!ownedBlocker;"
            "var value={ok:true};var failed=false;"
            f"if(p&&p.version==={self.adapter_version}&&typeof p.leaveCasePicker===\"function\"){{"
            "try{value=p.leaveCasePicker();}catch(_error){failed=true;}}"
            "var blocker=doc.getElementById('worktrace-fdwork-picker-blocker');"
            "if(blocker&&blocker.remove)blocker.remove();"
            "var toolbar=doc.getElementById('worktrace-fdwork-picker-toolbar');"
            "if(toolbar&&toolbar.remove)toolbar.remove();"
            "var fillBlocker=doc.getElementById('worktrace-fdwork-fill-blocker');"
            "if(fillBlocker&&fillBlocker.remove)fillBlocker.remove();"
            "if(restoreInput){var input=doc.querySelector('#basic_caseId');"
            "if(input&&input.disabled)input.disabled=false;}"
            "if(failed)return {ok:false,error:'javascript_exception'};"
            "return !value||value.ok!==false?{ok:true}:value;"
            "})()"
        )
        started_at = self._clock()
        value: Any = None
        internal_error_kind: str | None = None
        try:
            value = window.evaluate_js(script)
        except Exception as exc:
            kind = getattr(exc, "kind", None)
            internal_error_kind = (
                kind
                if isinstance(kind, str)
                and kind in {
                    "callback_timeout",
                    "executor_rejected",
                    "guard_rejected",
                    "javascript_exception",
                    "window_closed",
                    "navigation_changed",
                }
                else "javascript_exception"
            )
            value = {"ok": False, "error": internal_error_kind}
        result_type = type(value).__name__ if value is not None else "none"
        validated = self._validated_action_result(value, internal_error_kind)
        self._emit_action_diagnostic(
            action="leaveCasePicker",
            contract=contract,
            value=value,
            internal_error_kind=(
                None if validated.get("ok") is True else str(validated.get("error") or "dom_contract_changed")
            ),
            callback_executed=True,
            result_type=result_type,
            elapsed_ms=max(0, int((self._clock() - started_at) * 1000)),
        )
        return validated

    def leave_case_picker(
        self,
        window: Any,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        # Cleanup is local, synchronous and idempotent; do not depend on the
        # picker message/callback channel that may itself be the failed path.
        return self.reset_case_picker(window, contract)

    def fill_entry(self, window: Any, draft: Any, *, contract: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(super().fill_entry(window, draft, contract=contract))
        if result.get("ok") is not True and result.get("error") == "callback_timeout":
            # Once fillEntry was dispatched the Save click may already have
            # happened. A lost terminal callback must never invite blind retry.
            return {"ok": False, "error": "save_outcome_unknown"}
        return result

    def _ensure_picker_session(self, window: Any) -> Mapping[str, Any]:
        probe_script = (
            "(function(){"
            f"{_VERIFIED_WORK_SHELL_WINDOW_RESOLVER}"
            "var target=workTraceWorkShellWindow();"
            "if(!target)return {ok:false,error:'adapter_injection_failed'};"
            "var p=target.WorkTraceFDWorkPickerSession;"
            f"return {{ok:true,installed:!!(p&&p.version==={self.adapter_version})}};"
            "})()"
        )
        try:
            probe = window.evaluate_js(probe_script)
        except Exception:
            return {"ok": False, "error": "adapter_injection_failed"}
        if isinstance(probe, Mapping) and probe.get("installed") is True:
            return {"ok": True, "version": self.adapter_version}

        # Keep each dispatch small. Besides reducing WebView command pressure, this
        # avoids coupling the existing adapter cache/dispatch contract to the size
        # of the human-picker implementation.
        source = self.picker_source
        chunks = [source[index:index + 3500] for index in range(0, len(source), 3500)]
        if not chunks:
            return {"ok": False, "error": "adapter_injection_failed"}
        key = "__worktrace_fdwork_picker_source_v5"
        final: Any = None
        for index, chunk in enumerate(chunks):
            encoded = json.dumps(chunk, ensure_ascii=True)
            first = index == 0
            last = index == len(chunks) - 1
            body = (
                f"target.{key}=[{encoded}];" if first else f"target.{key}.push({encoded});"
            )
            if last:
                body += (
                    f"try{{target.eval(target.{key}.join(''));}}catch(_error){{"
                    f"try{{delete target.{key};}}catch(_ignored){{}}"
                    "return {ok:false,error:'adapter_injection_failed'};}"
                    f"try{{delete target.{key};}}catch(_ignored){{}}"
                    "var p=target.WorkTraceFDWorkPickerSession;"
                    f"return p&&p.version==={self.adapter_version}"
                    f"?{{ok:true,version:{self.adapter_version},installed:true}}"
                    ":{ok:false,error:'adapter_injection_failed'};"
                )
            else:
                body += "return {ok:true,staged:true};"
            script = (
                "(function(){"
                f"{_VERIFIED_WORK_SHELL_WINDOW_RESOLVER}"
                "var target=workTraceWorkShellWindow();"
                "if(!target)return {ok:false,error:'adapter_injection_failed'};"
                + body
                + "})()"
            )
            try:
                final = window.evaluate_js(script)
            except Exception:
                return {"ok": False, "error": "adapter_injection_failed"}
            if isinstance(final, Mapping) and final.get("ok") is False:
                return {"ok": False, "error": "adapter_injection_failed"}
        if isinstance(final, Mapping) and (
            final.get("installed") is True
            or final.get("version") == self.adapter_version
        ):
            return {"ok": True, "version": self.adapter_version}
        return {"ok": False, "error": "adapter_injection_failed"}


__all__ = ["FDWorkPageAdapter", "FDWorkPagePhase", "FDWorkPageType"]
