from __future__ import annotations

import inspect

import pytest

from worktrace.integrations.fd_work.helper_bridge import FDWorkHelperBridge


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Coordinator:
    def __init__(self) -> None:
        self.confirm_calls = []
        self.cancel_calls = []

    def confirm_case_picker(self, nonce, label):
        self.confirm_calls.append((nonce, label))
        return {"ok": True}

    def cancel_case_picker(self, nonce):
        self.cancel_calls.append(nonce)
        return {"ok": True}


def test_helper_bridge_is_narrow_and_exposes_no_application_services():
    public = {
        name
        for name, member in inspect.getmembers(FDWorkHelperBridge, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {"bind_coordinator", "confirm_case_picker", "cancel_case_picker"}


def test_helper_bridge_normalizes_only_valid_label_and_forwards_no_page_data():
    coordinator = _Coordinator()
    bridge = FDWorkHelperBridge(coordinator)

    assert bridge.confirm_case_picker("nonce-1", "\u3000CASE A\u00a0") == {"ok": True}
    assert coordinator.confirm_calls == [("nonce-1", "CASE A")]
    assert bridge.cancel_case_picker("nonce-1") == {"ok": True}
    assert coordinator.cancel_calls == ["nonce-1"]


@pytest.mark.parametrize(
    ("nonce", "label"),
    [
        (None, "CASE A"),
        ("", "CASE A"),
        ("n" * 257, "CASE A"),
        ("nonce", None),
        ("nonce", ""),
        ("nonce", "x" * 101),
    ],
)
def test_helper_bridge_rejects_invalid_nonce_or_label(nonce, label):
    coordinator = _Coordinator()
    bridge = FDWorkHelperBridge(coordinator)

    assert bridge.confirm_case_picker(nonce, label) == {
        "ok": False,
        "error": "invalid_picker_callback",
    }
    assert coordinator.confirm_calls == []


def test_unbound_helper_bridge_fails_closed():
    bridge = FDWorkHelperBridge()
    assert bridge.confirm_case_picker("nonce", "CASE A")["error"] == "picker_superseded"
    assert bridge.cancel_case_picker("nonce")["error"] == "picker_superseded"

