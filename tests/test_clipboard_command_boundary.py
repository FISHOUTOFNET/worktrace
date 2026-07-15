from __future__ import annotations

from unittest.mock import patch

import pytest

from worktrace.api import app_api, settings_api
from worktrace.services import privacy_gate_service
from worktrace.services.settings_service import set_setting
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


class _ClipboardRuntime:
    def __init__(self, events: list[tuple[str, bool]], *, accepted: bool = True) -> None:
        self.events = events
        self.accepted = accepted

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool:
        self.events.append(("runtime", bool(enabled)))
        return self.accepted


@pytest.fixture(autouse=True)
def _restore_runtime():
    previous = app_api.get_runtime()
    app_api.set_runtime(None)
    try:
        yield
    finally:
        app_api.set_runtime(previous)


def test_live_runtime_enable_requires_privacy_before_persistence(temp_db):
    events: list[tuple[str, bool]] = []
    app_api.set_runtime(_ClipboardRuntime(events))
    set_setting("first_run_notice_accepted", "false")
    set_setting("accepted_privacy_notice_version", "")

    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled_for_webview",
    ) as persist:
        result = WebViewBridge().set_clipboard_capture_enabled(True)

    assert result == {"ok": False, "error": "设置剪贴板记录失败"}
    assert events == []
    persist.assert_not_called()


def test_bridge_applies_runtime_before_persisting_preference(temp_db):
    privacy_gate_service.accept_privacy_notice()
    set_setting("clipboard_capture_enabled", "false")
    events: list[tuple[str, bool]] = []
    app_api.set_runtime(_ClipboardRuntime(events))

    def persist(enabled: bool):
        events.append(("persist", bool(enabled)))
        return {
            "ok": True,
            "status": {"clipboard_capture_enabled": bool(enabled)},
        }

    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled_for_webview",
        side_effect=persist,
    ):
        result = WebViewBridge().set_clipboard_capture_enabled(True)

    assert result["ok"] is True
    assert events == [("runtime", True), ("persist", True)]


def test_persistence_exception_compensates_runtime(temp_db):
    privacy_gate_service.accept_privacy_notice()
    set_setting("clipboard_capture_enabled", "false")
    events: list[tuple[str, bool]] = []
    app_api.set_runtime(_ClipboardRuntime(events))

    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled_for_webview",
        side_effect=RuntimeError("persistence failed"),
    ):
        result = WebViewBridge().set_clipboard_capture_enabled(True)

    assert result == {"ok": False, "error": "设置剪贴板记录失败"}
    assert events == [("runtime", True), ("runtime", False)]
    assert settings_api.is_clipboard_capture_enabled() is False


def test_persistence_rejection_compensates_and_preserves_stable_error(temp_db):
    privacy_gate_service.accept_privacy_notice()
    set_setting("clipboard_capture_enabled", "false")
    events: list[tuple[str, bool]] = []
    app_api.set_runtime(_ClipboardRuntime(events))
    rejection = {"ok": False, "error": "请选择有效的剪贴板记录状态"}

    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled_for_webview",
        return_value=rejection,
    ):
        result = WebViewBridge().set_clipboard_capture_enabled(True)

    assert result == rejection
    assert events == [("runtime", True), ("runtime", False)]


def test_runtime_rejection_never_persists_preference(temp_db):
    privacy_gate_service.accept_privacy_notice()
    events: list[tuple[str, bool]] = []
    app_api.set_runtime(_ClipboardRuntime(events, accepted=False))

    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled_for_webview",
    ) as persist:
        result = WebViewBridge().set_clipboard_capture_enabled(True)

    assert result == {"ok": False, "error": "设置剪贴板记录失败"}
    assert events == [("runtime", True)]
    persist.assert_not_called()
