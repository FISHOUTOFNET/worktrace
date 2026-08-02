from __future__ import annotations

import inspect

import pytest

from tests.support.application import build_test_bridge
from worktrace.webview_ui.bridge import WebViewBridge
from worktrace.integrations.fd_work.integration_service import FDWorkIntegrationService


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _FDWorkCapability:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.search_calls = []
        self.prepare_calls = []

    def get_settings_status(self):
        return {
            "supported": True, "enabled": True, "session_state": "ready",
            "operation": "none", "ready": True, "login_required": False,
            "error_code": None,
        }

    def search_cases(self, query, request_id):
        self.search_calls.append((query, request_id))
        return {"ok": True, "request_id": request_id, "options": [], "status": self.get_settings_status()}

    def prepare_session(self, show_login_if_required=True):
        self.prepare_calls.append(show_login_if_required)
        return {"ok": True, "status": self.get_settings_status()}

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
        return {"ok": True, "status": "opening"}


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

    assert result == {"ok": True, "status": "opening"}
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
        / "init.js"
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
    assert result["error"] == "renderer_unavailable"
    assert "WebView2" in result["message"]
    assert "表单" not in result["message"]


def test_independent_fd_work_bridge_exposes_status_search_and_existing_login_window():
    capability = _FDWorkCapability()
    bridge = build_test_bridge(fd_work=capability)

    status = bridge.get_fd_work_status()
    searched = bridge.search_fd_work_cases("CA", "request-1")
    login = bridge.show_fd_work_login()

    assert status["status"]["session_state"] == "ready"
    assert searched["request_id"] == "request-1"
    assert capability.search_calls == [("CA", "request-1")]
    assert login["ok"] is True
    assert capability.prepare_calls == [True]


@pytest.mark.parametrize("token", ["", "x" * 257, 7])
def test_rules_bridge_rejects_invalid_selection_token_before_capability(token):
    bridge = build_test_bridge()
    result = bridge.create_project_for_rules("CASE A", "", "中文", token)
    assert result == {"ok": False, "error": "操作无效"}
