from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from worktrace.webview_ui.bridge import WebViewBridge


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _FDWorkCapability:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def open_entry(
        self,
        report_date: str,
        projection_instance_key: str,
        expected_projection_revision: str,
        expected_source_version: str,
    ):
        self.calls.append(
            (
                report_date,
                projection_instance_key,
                expected_projection_revision,
                expected_source_version,
            )
        )
        return {"ok": True, "status": "opening"}


def _bridge(capability: _FDWorkCapability) -> WebViewBridge:
    services = SimpleNamespace(
        fd_work=capability,
        app_control=SimpleNamespace(
            get_collection_status=lambda: {},
        ),
        runtime_view=object(),
    )
    return WebViewBridge(services)


def test_shipping_method_accepts_identity_and_versions_only():
    parameters = list(inspect.signature(WebViewBridge.open_fd_work_entry).parameters)
    assert parameters == [
        "self",
        "report_date",
        "projection_instance_key",
        "expected_projection_revision",
        "expected_source_version",
    ]


def test_bridge_forwards_no_remote_field_values_or_adapter_knowledge():
    capability = _FDWorkCapability()
    bridge = _bridge(capability)

    result = bridge.open_fd_work_entry(
        "2026-07-31",
        "base:closed",
        "projection-revision",
        "source-version",
    )

    assert result == {"ok": True, "status": "opening"}
    assert capability.calls == [
        (
            "2026-07-31",
            "base:closed",
            "projection-revision",
            "source-version",
        )
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        ("31/07/2026", "base:closed", "revision", "source"),
        ("2026-07-31", "", "revision", "source"),
        ("2026-07-31", "base:closed", "", "source"),
        ("2026-07-31", "base:closed", "revision", ""),
    ],
)
def test_invalid_transport_does_not_reach_application_capability(arguments):
    capability = _FDWorkCapability()
    bridge = _bridge(capability)

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
