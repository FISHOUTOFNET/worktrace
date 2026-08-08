from __future__ import annotations

import inspect

import pytest

from tests.support.application import build_test_bridge
from worktrace.webview_ui.bridge import SHIPPING_METHODS, WebViewBridge
from worktrace.integrations.fd_work.integration_service import FDWorkIntegrationService
from worktrace.webview_ui.bridge_fd_work import fd_work_message


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _FDWorkCapability:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.picker_calls = []
        self.prepare_calls = []

    def get_settings_status(self):
        return {
            "supported": True, "enabled": True, "session_state": "ready",
            "operation": "none", "ready": True, "login_required": False,
            "error_code": None,
        }

    def open_case_picker(self, request_id):
        self.picker_calls.append(request_id)
        return {
            "ok": True,
            "request_id": request_id,
            "operation_status": "picker_ready",
            "capability_status": self.get_settings_status(),
        }

    def prepare_session(self, show_login_if_required=True):
        self.prepare_calls.append(show_login_if_required)
        return {"ok": True, "capability_status": self.get_settings_status()}

    def open_entry(
        self,
        report_date: str,
        projection_instance_key: str,
        expected_projection_revision: str,
    ):
        self.calls.append(
            (
                report_date,
                projection_instance_key,
                expected_projection_revision,
            )
        )
        return {
            "ok": True,
            "operation_status": "saved",
            "capability_status": self.get_settings_status(),
        }


def test_shipping_method_accepts_identity_and_versions_only():
    parameters = list(inspect.signature(WebViewBridge.open_fd_work_entry).parameters)
    assert parameters == [
        "self",
        "report_date",
        "projection_instance_key",
        "expected_projection_revision",
    ]


def test_bridge_forwards_no_remote_field_values_or_adapter_knowledge():
    capability = _FDWorkCapability()
    bridge = build_test_bridge(fd_work=capability)

    result = bridge.open_fd_work_entry(
        "2026-07-31",
        "base:closed",
        "projection-revision",
    )

    assert result["ok"] is True
    assert result["operation_status"] == "saved"
    assert result["capability_status"]["session_state"] == "ready"
    assert "status" not in result
    assert capability.calls == [
        (
            "2026-07-31",
            "base:closed",
            "projection-revision",
        )
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        ("31/07/2026", "base:closed", "revision"),
        ("2026-07-31", "", "revision"),
        ("2026-07-31", "base:closed", ""),
    ],
)
def test_invalid_transport_does_not_reach_application_capability(arguments):
    capability = _FDWorkCapability()
    bridge = build_test_bridge(fd_work=capability)

    result = bridge.open_fd_work_entry(*arguments)

    assert result["ok"] is False
    assert result["error"] == "invalid_input"
    assert capability.calls == []


def test_frontend_bridge_contract_has_no_remote_payload_arguments():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "worktrace"
        / "webview_ui"
        / "js"
        / "init_fd_work_v5.js"
    ).read_text(encoding="utf-8")
    assert 'openFDWorkEntry: fixedBridgeMethod("open_fd_work_entry")' in source
    for forbidden in (
        "case_number",
        "project_name",
        "narrative",
        "duration_hours",
        "fd_work_url",
        "selector",
        "javascript",
    ):
        assert forbidden not in inspect.signature(
            WebViewBridge.open_fd_work_entry
        ).parameters


def test_direct_bridge_call_cannot_bypass_disabled_capability():
    bridge = build_test_bridge(
        fd_work=FDWorkIntegrationService(enabled_reader=lambda: False)
    )

    result = bridge.open_fd_work_entry(
        "2026-07-31",
        "base:closed",
        "projection-revision",
    )

    assert result == {
        "ok": False,
        "error": "fd_work_disabled",
        "message": "FD Work 插件已关闭，请在高级设置中开启",
    }


def test_renderer_unavailable_is_not_reported_as_a_form_error():
    capability = _FDWorkCapability()
    capability.open_entry = lambda *_args: {
        "ok": False,
        "error": "renderer_unavailable",
    }
    bridge = build_test_bridge(fd_work=capability)

    result = bridge.open_fd_work_entry(
        "2026-07-31",
        "base:closed",
        "projection-revision",
    )

    assert result["ok"] is False
    assert result["error"] == "fd_work_window_unavailable"
    assert "WebView2" in result["message"]
    assert "表单" not in result["message"]


def test_main_bridge_exposes_explicit_picker_and_existing_login_window_only():
    capability = _FDWorkCapability()
    bridge = build_test_bridge(fd_work=capability)

    status = bridge.get_fd_work_status()
    opened = bridge.open_fd_work_case_picker("request-1")
    login = bridge.show_fd_work_login()

    assert status["status"]["session_state"] == "ready"
    assert opened["request_id"] == "request-1"
    assert capability.picker_calls == ["request-1"]
    assert login["ok"] is True
    assert capability.prepare_calls == [True]


def test_shipping_bridge_has_no_inline_fd_work_search_method():
    assert not hasattr(WebViewBridge, "search_fd_work_cases")
    assert "search_fd_work_cases" not in SHIPPING_METHODS


def test_persistent_binding_and_removed_remote_case_have_actionable_messages():
    assert fd_work_message("project_not_fd_work_bound") == (
        "当前项目未关联 FD Work 案件，请在“项目规则”中编辑项目并从 FD Work 案件列表中选择。"
    )
    assert fd_work_message("case_not_found") == (
        "已关联的 FD Work 案件当前不可用，请在项目规则中重新关联。"
    )


@pytest.mark.parametrize(
    ("code", "message_part"),
    [
        ("case_input_missing", "案件输入框"),
        ("case_input_not_interactive", "尚未准备"),
        ("case_input_not_rendered", "尚未显示"),
        ("case_aria_controls_missing", "页面结构"),
        ("case_popup_not_created", "下拉框"),
        ("case_popup_not_interactive", "下拉框"),
        ("case_query_not_applied", "搜索内容"),
        ("case_results_stale", "结果尚未刷新"),
        ("case_results_timeout", "搜索超时"),
    ],
)
def test_lookup_stage_errors_have_actionable_messages(code, message_part):
    assert message_part in fd_work_message(code)


@pytest.mark.parametrize("token", ["", "x" * 257, 7])
def test_rules_bridge_rejects_invalid_selection_token_before_capability(token):
    bridge = build_test_bridge()
    result = bridge.create_project_for_rules("CASE A", "", "中文", token)
    assert result == {"ok": False, "error": "操作无效"}
