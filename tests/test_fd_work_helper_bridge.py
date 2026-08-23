from __future__ import annotations

import inspect

import pytest

from worktrace.integrations.fd_work.helper_bridge import FDWorkHelperBridge


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Coordinator:
    def __init__(self) -> None:
        self.confirm_calls = []
        self.cancel_calls = []

    def submit_case_picker_confirmation(self, nonce, label, revision):
        self.confirm_calls.append((nonce, label, revision))
        return {"ok": True, "accepted": True}

    def submit_case_picker_cancellation(self, nonce):
        self.cancel_calls.append(nonce)
        return {"ok": True, "accepted": True}


class _ActionResultSink:
    def __init__(self) -> None:
        self.calls = []

    def submit_adapter_action_result(self, nonce, action, result):
        self.calls.append((nonce, action, result))
        return True


def test_helper_bridge_is_narrow_and_exposes_no_application_services():
    public = {
        name
        for name, member in inspect.getmembers(FDWorkHelperBridge, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {
        "bind_coordinator",
        "submit_adapter_action_result",
        "submit_case_picker_confirmation",
        "submit_case_picker_cancellation",
    }


def test_adapter_action_result_bridge_only_validates_and_signals_bound_sink():
    coordinator = _Coordinator()
    sink = _ActionResultSink()
    bridge = FDWorkHelperBridge(coordinator, action_result_sink=sink)

    response = bridge.submit_adapter_action_result(
        "action-nonce",
        "enterCasePicker",
        {"ok": True, "status": "picker_ready"},
    )

    assert response == {"ok": True, "accepted": True}
    assert sink.calls == [
        (
            "action-nonce",
            "enterCasePicker",
            {"ok": True, "status": "picker_ready"},
        )
    ]
    assert coordinator.confirm_calls == []
    assert coordinator.cancel_calls == []


@pytest.mark.parametrize(
    ("nonce", "action", "result"),
    [
        (None, "enterCasePicker", {"ok": True}),
        ("", "enterCasePicker", {"ok": True}),
        ("n" * 257, "enterCasePicker", {"ok": True}),
        ("nonce", "unknownAction", {"ok": True}),
        ("nonce", "enterCasePicker", None),
        ("nonce", "enterCasePicker", {"ok": "yes"}),
        ("nonce", "enterCasePicker", {"ok": True, "status": "x" * 65}),
        ("nonce", "readSelectedCase", {"ok": True, "label": "x" * 101}),
    ],
)
def test_adapter_action_result_bridge_rejects_invalid_transport(nonce, action, result):
    sink = _ActionResultSink()
    bridge = FDWorkHelperBridge(action_result_sink=sink)

    assert bridge.submit_adapter_action_result(nonce, action, result) == {
        "ok": False,
        "error": "invalid_adapter_callback",
    }
    assert sink.calls == []


def test_helper_bridge_normalizes_only_valid_label_and_forwards_no_page_data():
    coordinator = _Coordinator()
    bridge = FDWorkHelperBridge(coordinator)

    assert bridge.submit_case_picker_confirmation(
        "nonce-1", "\u3000CASE A\u00a0", 3
    ) == {"ok": True, "accepted": True}
    assert coordinator.confirm_calls == [("nonce-1", "CASE A", 3)]
    assert bridge.submit_case_picker_cancellation("nonce-1") == {
        "ok": True,
        "accepted": True,
    }
    assert coordinator.cancel_calls == ["nonce-1"]


@pytest.mark.parametrize(
    ("nonce", "label", "revision"),
    [
        (None, "CASE A", 1),
        ("", "CASE A", 1),
        ("n" * 257, "CASE A", 1),
        ("nonce", None, 1),
        ("nonce", "", 1),
        ("nonce", "x" * 101, 1),
        ("nonce", "CASE A", True),
        ("nonce", "CASE A", 0),
        ("nonce", "CASE A", 1_000_001),
    ],
)
def test_helper_bridge_rejects_invalid_nonce_label_or_revision(nonce, label, revision):
    coordinator = _Coordinator()
    bridge = FDWorkHelperBridge(coordinator)

    assert bridge.submit_case_picker_confirmation(nonce, label, revision) == {
        "ok": False,
        "error": "invalid_picker_callback",
    }
    assert coordinator.confirm_calls == []


def test_unbound_helper_bridge_fails_closed():
    bridge = FDWorkHelperBridge()
    assert bridge.submit_case_picker_confirmation(
        "nonce", "CASE A", 1
    )["error"] == "picker_superseded"
    assert bridge.submit_case_picker_cancellation(
        "nonce"
    )["error"] == "picker_superseded"
