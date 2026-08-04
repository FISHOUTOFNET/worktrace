from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.page_adapter import FDWorkPageAdapter, FDWorkPageType
from worktrace.integrations.fd_work.window_executor import (
    FDWorkExecutorWindow,
    FDWorkWindowExecutor,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


def _operation(**overrides):
    value = {
        "operation_nonce": "nonce",
        "operation_generation": 2,
        "navigation_generation": 3,
        "timeout_seconds": 1.0,
        "operation_deadline_ms": 1893456000000,
    }
    value.update(overrides)
    return value


def _draft():
    return FDWorkEntryDraft("2026-08-03", 'CASE-"quoted"', "1.5", "Narrative")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://work.fangdalaw.com/Works/WorkHourList?picker=day", FDWorkPageType.WORK_HOUR_LIST),
        ("https://work.fangdalaw.com/Login", FDWorkPageType.LOGIN),
        ("https://work.fangdalaw.com/LoginToken", FDWorkPageType.LOGIN),
        ("https://work.fangdalaw.com/permission", FDWorkPageType.UNAUTHORIZED),
        ("https://work.fangdalaw.com/404", FDWorkPageType.ERROR),
        ("https://example.com/login", FDWorkPageType.UNKNOWN),
    ],
)
def test_page_type_and_navigation_are_fail_closed(url, expected):
    adapter = FDWorkPageAdapter()
    assert adapter.detect_page(url) is expected
    assert adapter.navigation_allowed(url) is (url.startswith("https://work.fangdalaw.com/"))


def test_login_and_confirmation_are_distinct_and_login_url_is_derived():
    adapter = FDWorkPageAdapter()
    assert adapter.detect_page_hint("https://work.fangdalaw.com/Login") == "login_credentials"
    assert adapter.detect_page_hint("https://work.fangdalaw.com/LoginToken") == "login_confirmation"
    business = urlsplit(adapter.business_url)
    login = urlsplit(adapter.login_url)
    assert parse_qs(login.query) == {"returnUrl": [business.path + "?" + business.query]}


def test_adapter_v5_owns_selectors_and_cached_asset():
    adapter = FDWorkPageAdapter()
    assert adapter.adapter_version == 5
    assert set(adapter.field_contract) == {
        "case_number", "work_date", "duration_hours", "narrative"
    }
    assert Path(adapter.adapter_asset_path).name == "fd_work_adapter.js"


def test_page_phase_probe_has_no_interactive_handshake_or_dom_mutation():
    scripts = []

    class Window:
        def evaluate_js(self, script, callback=None):
            assert callback is None
            scripts.append(script)
            return {"phase": "work_shell"}

    values = []
    FDWorkPageAdapter().probe_page_phase(Window(), values.append)
    assert values == [{"phase": "work_shell"}]
    assert "work_shell" in scripts[0]
    assert "document.querySelector('#basic_caseId')" in scripts[0]
    assert '#basic_caseId[role="combobox"]' not in scripts[0]
    assert '.ant-select[name="workhours/matter/selector"]' in scripts[0]
    assert "form.contains(matter)" in scripts[0]
    for safe_field in ("form_exists", "wrapper_exists", "role_matches"):
        assert safe_field in scripts[0]
    assert "work_interactive" not in scripts[0]
    for forbidden in (".focus(", ".click(", "KeyboardEvent", ".blur("):
        assert forbidden not in scripts[0]


class _Window:
    def __init__(self, action_result):
        self.action_result = action_result
        self.calls = []

    def evaluate_js(self, script, callback=None):
        self.calls.append((script, callback))
        if callback is not None:
            callback(self.action_result)
            return None
        return {"ok": True, "version": 5}


def test_picker_actions_use_small_v5_scripts_and_validate_selected_label():
    adapter = FDWorkPageAdapter()
    window = _Window({"ok": True, "label": "\u3000CASE A\u00a0"})
    assert adapter.install_adapter(window) == {"ok": True, "version": 5}
    assert adapter.read_selected_case(window, _operation()) == {"ok": True, "label": "CASE A"}
    script = window.calls[-1][0]
    assert "readSelectedCase" in script
    assert '"version":5' in script
    assert '"operation_nonce":"nonce"' in script
    assert '"operation_deadline_ms":1893456000000' in script
    assert len(script) < 3000


@pytest.mark.parametrize(
    ("method", "remote_result", "expected_error"),
    [
        ("read_selected_case", {"ok": False, "error": "case_selection_required"}, "case_selection_required"),
        ("read_selected_case", {"ok": True, "label": ""}, "dom_contract_changed"),
        ("enter_case_picker", {"ok": False, "error": "fd_work_busy"}, "fd_work_busy"),
        ("await_stable_work_shell", {"ok": False, "error": "lookup_superseded"}, "lookup_superseded"),
    ],
)
def test_picker_and_stable_actions_fail_closed(method, remote_result, expected_error):
    adapter = FDWorkPageAdapter()
    value = getattr(adapter, method)(_Window(remote_result), _operation())
    assert value["ok"] is False
    assert value["error"] == expected_error


def test_fill_serializes_only_four_allowed_values_and_uses_v5_contract():
    window = _Window({"ok": True, "status": "filled"})
    adapter = FDWorkPageAdapter()

    result = adapter.fill_entry(window, _draft(), contract=_operation())

    assert result == {"ok": True, "status": "filled"}
    script = window.calls[-1][0]
    for key in ("work_date", "case_number", "duration_hours", "narrative"):
        assert key in script
    assert "fillEntry" in script
    assert 'CASE-\\\"quoted\\\"' in script
    for forbidden in ("cookie", "localStorage", "sessionStorage"):
        assert forbidden not in script


def test_adapter_source_is_cached_and_actions_do_not_reinject(monkeypatch):
    reads = []
    original = Path.read_text

    def tracked(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked)
    adapter = FDWorkPageAdapter()
    window = _Window({"ok": True, "status": "stable"})
    adapter.install_adapter(window)
    adapter.install_adapter(window)
    adapter.await_stable_work_shell(window, _operation())
    adapter.enter_case_picker(window, _operation())
    assert len(reads) == 1
    assert sum(len(script) > 10_000 for script, callback in window.calls if callback is None) == 2
    assert sum(callable(callback) for _script, callback in window.calls) == 2


def test_action_diagnostics_distinguish_javascript_exception_without_page_data():
    diagnostics = []

    class Window:
        def evaluate_js(self, _script, callback=None):
            del callback
            raise RuntimeError("page value and markup must not be logged")

    adapter = FDWorkPageAdapter(diagnostic_callback=diagnostics.append)

    result = adapter.enter_case_picker(Window(), _operation())

    assert result == {"ok": False, "error": "javascript_exception"}
    assert diagnostics == [
        {
            "action": "enterCasePicker",
            "internal_error_kind": "javascript_exception",
            "elapsed_ms": pytest.approx(0, abs=100),
            "adapter_version": 5,
            "operation_generation": 2,
            "navigation_generation": 3,
            "callback_executed": False,
            "result_type": "none",
        }
    ]
    serialized = repr(diagnostics)
    assert "page value" not in serialized
    assert "markup" not in serialized


def test_action_diagnostics_distinguish_callback_timeout_and_ignore_stale_callback():
    diagnostics = []
    callbacks = []

    class Window:
        def evaluate_js(self, _script, callback=None):
            callbacks.append(callback)

    adapter = FDWorkPageAdapter(diagnostic_callback=diagnostics.append)
    operation = _operation(timeout_seconds=0.01, operation_deadline_ms=1)

    result = adapter.enter_case_picker(Window(), operation)
    callbacks[0]({"ok": True, "status": "picker_ready", "label": "PRIVATE"})

    assert result == {"ok": False, "error": "callback_timeout"}
    assert len(diagnostics) == 1
    assert diagnostics[0]["internal_error_kind"] == "callback_timeout"
    assert diagnostics[0]["callback_executed"] is False
    assert diagnostics[0]["result_type"] == "none"
    assert "PRIVATE" not in repr(diagnostics)


def test_action_diagnostics_distinguish_non_mapping_callback_result():
    diagnostics = []
    adapter = FDWorkPageAdapter(diagnostic_callback=diagnostics.append)
    window = _Window("not-a-mapping")

    result = adapter.enter_case_picker(window, _operation())

    assert result == {"ok": False, "error": "non_mapping_result"}
    assert diagnostics[0]["internal_error_kind"] == "non_mapping_result"
    assert diagnostics[0]["callback_executed"] is True
    assert diagnostics[0]["result_type"] == "str"


def test_executor_javascript_exception_keeps_specific_internal_diagnostic():
    diagnostics = []
    executor = FDWorkWindowExecutor(name="fd-work-page-adapter-test")

    class Window:
        def evaluate_js(self, _script, callback=None):
            del callback
            raise RuntimeError("unsafe page exception text")

    guarded = FDWorkExecutorWindow(Window(), executor, lambda: True)
    result = FDWorkPageAdapter(
        diagnostic_callback=diagnostics.append
    ).enter_case_picker(guarded, _operation())

    assert result == {"ok": False, "error": "javascript_exception"}
    assert diagnostics[0]["internal_error_kind"] == "javascript_exception"
    assert "unsafe page exception text" not in repr(diagnostics)
    executor.shutdown(timeout=1)
