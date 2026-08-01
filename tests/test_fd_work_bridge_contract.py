from __future__ import annotations

import inspect

import pytest

from tests.support.application import build_test_bridge
from worktrace.webview_ui.bridge import WebViewBridge
from worktrace.integrations.fd_work.entry_service import FDWorkEntryService


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _FDWorkCapability:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

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
        fd_work=FDWorkEntryService(enabled_reader=lambda: False)
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
