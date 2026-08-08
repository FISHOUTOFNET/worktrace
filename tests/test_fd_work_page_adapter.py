from __future__ import annotations

from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.page_adapter import FDWorkPageAdapter, FDWorkPageType
from worktrace.integrations.fd_work.window_executor import (
    FDWorkExecutorWindow,
    FDWorkWindowExecutor,
)


pytestmark = [
    pytest.mark.unit,
    pytest.mark.collector_runtime,
    pytest.mark.contract,
    pytest.mark.parallel_safe,
]


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
    return FDWorkEntryDraft(
        work_date="2026-08-03",
        case_label='#26IP0165 CASE-"quoted"',
        case_query="26IP0165",
        duration_hours="1.5",
        narrative="Narrative",
    )


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
    assert set(adapter.page_context_contract) == {"work_date"}
    assert set(adapter.entry_field_contract) == {
        "case_number", "duration_hours", "narrative"
    }
    date_contract = adapter.page_context_contract["work_date"]
    assert date_contract["selector"] == 'input[placeholder="请选择日期"]'
    assert date_contract["outside_form_selector"] == "form#basic"
    assert date_contract["previous_button_icon"] == "left"
    assert date_contract["next_button_icon"] == "right"
    assert "form#basic" not in date_contract["selector"]
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
    assert 'pathname' in scripts[0]
    assert '"/works/workhourlist"' in scripts[0]
    assert "frame.contentWindow" in scripts[0]
    assert "candidate.document.body" in scripts[0]
    for safe_field in ("body_exists", "work_page_candidate_count", "editor_exists"):
        assert safe_field in scripts[0]
    assert "form#basic" not in scripts[0]
    assert "#basic_caseId" not in scripts[0]
    assert "work_interactive" not in scripts[0]
    for forbidden in (".focus(", ".click(", "KeyboardEvent", ".blur("):
        assert forbidden not in scripts[0]


class _Window:
    def __init__(self, adapter, action_result, *, dispatch_result=None):
        self.adapter = adapter
        self.action_result = action_result
        self.dispatch_result = dispatch_result or {"ok": True, "status": "dispatched"}
        self.calls = []

    def evaluate_js(self, script, callback=None):
        self.calls.append((script, callback))
        if callback is not None:
            callback(self.dispatch_result)
            nonce = re.search(r'"action_nonce":"([^"]+)"', script).group(1)
            action = re.search(r'"action":"([^"]+)"', script).group(1)
            if isinstance(self.action_result, dict):
                self.adapter.submit_adapter_action_result(
                    nonce,
                    action,
                    self.action_result,
                )
            return None
        return {"ok": True, "version": 5}


def test_picker_actions_use_small_v5_scripts_and_validate_selected_label():
    adapter = FDWorkPageAdapter()
    window = _Window(adapter, {"ok": True, "label": "\u3000CASE A\u00a0"})
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
        ("await_stable_work_page", {"ok": False, "error": "lookup_superseded"}, "lookup_superseded"),
        ("ensure_entry_editor", {"ok": False, "error": "entry_create_action_missing"}, "entry_create_action_missing"),
        ("await_stable_entry_editor", {"ok": False, "error": "entry_editor_not_rendered"}, "entry_editor_not_rendered"),
    ],
)
def test_picker_and_stable_actions_fail_closed(method, remote_result, expected_error):
    adapter = FDWorkPageAdapter()
    value = getattr(adapter, method)(_Window(adapter, remote_result), _operation())
    assert value["ok"] is False
    assert value["error"] == expected_error


def test_fill_serializes_separate_case_label_and_query_with_v5_contract():
    adapter = FDWorkPageAdapter()
    window = _Window(adapter, {"ok": True, "status": "saved"})

    result = adapter.fill_entry(window, _draft(), contract=_operation())

    assert result == {"ok": True, "status": "saved"}
    script = window.calls[-1][0]
    for key in ("work_date", "case_label", "case_query", "duration_hours", "narrative"):
        assert key in script
    assert "fillEntry" in script
    assert '#26IP0165 CASE-\\\"quoted\\\"' in script
    assert '"case_query":"26IP0165"' in script
    assert '"page_context"' in script
    assert '"entry_fields"' in script
    assert '"work_date"' in script
    assert '"outside_form_selector":"form#basic"' in script
    for forbidden in ("cookie", "localStorage", "sessionStorage"):
        assert forbidden not in script


def test_fill_diagnostics_preserve_privacy_safe_stage_without_page_values():
    diagnostics = []
    adapter = FDWorkPageAdapter(diagnostic_callback=diagnostics.append)
    window = _Window(
        adapter,
        {
            "ok": False,
            "error": "case_popup_not_created",
            "stage": "case_open",
            "internal_error_kind": "case_popup_not_created",
            "option_count": 0,
            "commit_method": "semantic_click",
            "commit_attempt_count": 1,
            "option_connected_before_action": True,
            "option_connected_after_action": False,
            "popup_replaced": True,
            "live_option_reacquired": True,
        },
    )

    result = adapter.fill_entry(window, _draft(), contract=_operation())

    assert result == {
        "ok": False,
        "error": "case_popup_not_created",
        "stage": "case_open",
        "option_count": 0,
        "commit_method": "semantic_click",
        "commit_attempt_count": 1,
        "option_connected_before_action": True,
        "option_connected_after_action": False,
        "popup_replaced": True,
        "live_option_reacquired": True,
    }
    assert diagnostics[-1]["action"] == "fill_entry"
    assert diagnostics[-1]["stage"] == "case_open"
    assert diagnostics[-1]["internal_error_kind"] == "case_popup_not_created"
    assert diagnostics[-1]["option_count"] == 0
    assert diagnostics[-1]["commit_method"] == "semantic_click"
    assert diagnostics[-1]["commit_attempt_count"] == 1
    assert diagnostics[-1]["option_connected_before_action"] is True
    assert diagnostics[-1]["option_connected_after_action"] is False
    assert diagnostics[-1]["popup_replaced"] is True
    assert diagnostics[-1]["live_option_reacquired"] is True
    serialized = repr(diagnostics)
    assert _draft().case_label not in serialized
    assert _draft().case_query not in serialized
    assert _draft().narrative not in serialized


def test_adapter_source_is_cached_and_actions_do_not_reinject(monkeypatch):
    reads = []
    original = Path.read_text

    def tracked(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked)
    adapter = FDWorkPageAdapter()
    window = _Window(adapter, {"ok": True, "status": "stable"})
    adapter.install_adapter(window)
    adapter.install_adapter(window)
    adapter.await_stable_work_shell(window, _operation())
    adapter.enter_case_picker(window, _operation())
    assert len(reads) == 1
    assert sum(len(script) > 10_000 for script, callback in window.calls if callback is None) == 2
    assert sum(callable(callback) for _script, callback in window.calls) == 2


def test_adapter_install_and_actions_resolve_bounded_same_origin_work_shell_frame():
    adapter = FDWorkPageAdapter()
    window = _Window(adapter, {"ok": True, "status": "picker_ready"})

    assert adapter.install_adapter(window) == {"ok": True, "version": 5}
    install_script = window.calls[-1][0]
    assert "frame.contentWindow" in install_script
    assert "target.eval" in install_script
    assert "windows.length < 16" in install_script
    install_resolver = install_script.split("var target=", 1)[0]
    assert '"/works/workhourlist"' in install_resolver
    assert "form#basic" not in install_resolver
    assert "#basic_caseId" not in install_resolver

    adapter.enter_case_picker(window, _operation())
    action_script = window.calls[-1][0]
    assert "target&&target.WorkTraceFDWorkAdapter" in action_script
    assert "windows.length < 16" in action_script
    action_resolver = action_script.split("var target=", 1)[0]
    assert '"/works/workhourlist"' in action_resolver
    assert "form#basic" not in action_resolver
    assert "#basic_caseId" not in action_resolver
    assert "target.postMessage" in action_script
    assert "worktrace-fdwork-action-v5" in action_script
    assert "action_nonce" in action_script
    assert '"action":"enterCasePicker"' in action_script
    for forbidden in (
        "return new Promise(function(resolve)",
        "target.Promise.resolve(value)",
        "return a.enterCasePicker",
        "target.eval",
        "__worktrace_fdwork_action_result_v5",
    ):
        assert forbidden not in action_script

    adapter.await_stable_work_page(window, _operation())
    asynchronous_script = window.calls[-1][0]
    assert "target.postMessage" in asynchronous_script
    assert '"action":"awaitStableWorkPage"' in asynchronous_script
    assert "return new Promise(function(resolve)" not in asynchronous_script


def test_entry_editor_actions_are_one_shared_adapter_contract():
    adapter = FDWorkPageAdapter()
    window = _Window(adapter, {"ok": True, "status": "entry_editor_ready"})

    assert adapter.ensure_entry_editor(window, _operation())["ok"] is True
    assert '"action":"ensureEntryEditor"' in window.calls[-1][0]
    assert adapter.await_stable_entry_editor(window, _operation())["ok"] is True
    assert '"action":"awaitStableEntryEditor"' in window.calls[-1][0]


def test_post_message_action_waits_for_bridge_result_without_window_reentry():
    dispatched = threading.Event()
    result = {}
    scripts = []
    adapter = FDWorkPageAdapter(nonce_factory=lambda: "action-nonce")

    class Window:
        def evaluate_js(self, script, callback=None):
            scripts.append(script)
            callback({"ok": True, "status": "dispatched"})
            dispatched.set()

    worker = threading.Thread(
        target=lambda: result.setdefault(
            "value",
            adapter.enter_case_picker(Window(), _operation()),
        )
    )
    worker.start()
    assert dispatched.wait(timeout=1)

    assert adapter.submit_adapter_action_result(
        "action-nonce",
        "enterCasePicker",
        {"ok": True, "status": "picker_ready"},
    ) is True
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result["value"] == {"ok": True, "status": "picker_ready"}
    assert len(scripts) == 1


def test_navigation_cancels_pending_action_and_late_bridge_result_is_discarded():
    dispatched = threading.Event()
    result = {}
    adapter = FDWorkPageAdapter(nonce_factory=lambda: "action-nonce")

    class Window:
        def evaluate_js(self, _script, callback=None):
            callback({"ok": True, "status": "dispatched"})
            dispatched.set()

    worker = threading.Thread(
        target=lambda: result.setdefault(
            "value",
            adapter.enter_case_picker(Window(), _operation(timeout_seconds=1)),
        )
    )
    worker.start()
    assert dispatched.wait(timeout=1)
    adapter.cancel_pending_actions("navigation_changed")
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result["value"] == {"ok": False, "error": "navigation_changed"}
    assert adapter.submit_adapter_action_result(
        "action-nonce",
        "enterCasePicker",
        {"ok": True, "status": "picker_ready"},
    ) is False


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
    scripts = []

    class Window:
        def evaluate_js(self, script, callback=None):
            scripts.append(script)
            callback({"ok": True, "status": "dispatched"})

    adapter = FDWorkPageAdapter(diagnostic_callback=diagnostics.append)
    operation = _operation(timeout_seconds=0.01, operation_deadline_ms=1)

    result = adapter.enter_case_picker(Window(), operation)
    nonce = re.search(r'"action_nonce":"([^"]+)"', scripts[0]).group(1)
    accepted = adapter.submit_adapter_action_result(
        nonce,
        "enterCasePicker",
        {"ok": True, "status": "picker_ready", "label": "PRIVATE"},
    )

    assert result == {"ok": False, "error": "callback_timeout"}
    assert accepted is False
    assert len(diagnostics) == 1
    assert diagnostics[0]["internal_error_kind"] == "callback_timeout"
    assert diagnostics[0]["callback_executed"] is False
    assert diagnostics[0]["result_type"] == "none"
    assert "PRIVATE" not in repr(diagnostics)


def test_action_diagnostics_distinguish_non_mapping_dispatch_result():
    diagnostics = []
    adapter = FDWorkPageAdapter(diagnostic_callback=diagnostics.append)
    window = _Window(adapter, None, dispatch_result="not-a-mapping")

    result = adapter.enter_case_picker(window, _operation())

    assert result == {"ok": False, "error": "non_mapping_result"}
    assert diagnostics[0]["internal_error_kind"] == "non_mapping_result"
    assert diagnostics[0]["callback_executed"] is False
    assert diagnostics[0]["result_type"] == "none"


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
