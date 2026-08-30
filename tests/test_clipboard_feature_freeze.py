"""Shipping contracts for the temporarily unavailable clipboard capability."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from worktrace.api import settings_api
from worktrace.constants import CLIPBOARD_CAPTURE_AVAILABLE
from worktrace.platforms import windows_clipboard
from worktrace.platforms.windows_adapter import WindowsAdapter
from worktrace.platforms.windows_clipboard import ClipboardMonitor
from worktrace.services.settings_service import set_setting

pytestmark = [pytest.mark.contract, pytest.mark.db]
ROOT = Path(__file__).resolve().parents[1]


class _PathResolver:
    def reset(self) -> None:
        return None


class _Health:
    def __init__(self) -> None:
        self.succeeded_calls = 0
        self.paused: list[bool] = []

    def succeeded(self) -> None:
        self.succeeded_calls += 1

    def failed(self, _code: str) -> None:
        raise AssertionError("unavailable clipboard worker must not fail")

    def maintenance_paused(self, paused: bool) -> None:
        self.paused.append(bool(paused))


def test_shipping_clipboard_capability_is_frozen() -> None:
    assert CLIPBOARD_CAPTURE_AVAILABLE is False


def test_settings_api_rejects_enabling_frozen_clipboard(temp_db) -> None:
    set_setting("clipboard_capture_enabled", "false")

    result = settings_api.set_clipboard_capture_enabled_for_webview(True)

    assert result == {
        "ok": False,
        "error": "剪贴板记录暂未开放",
        "error_code": "clipboard_capture_unavailable",
    }
    assert settings_api.is_clipboard_capture_enabled() is False


def test_shipping_windows_adapter_cannot_enable_clipboard_monitor() -> None:
    adapter = WindowsAdapter(path_resolver=_PathResolver())

    adapter.set_clipboard_capture_enabled(True)

    assert adapter._clipboard._enabled is False
    assert adapter.get_clipboard_events() == []


def test_frozen_worker_never_touches_windows_clipboard(monkeypatch) -> None:
    source_calls = 0

    def source_window():
        nonlocal source_calls
        source_calls += 1
        raise AssertionError("frozen clipboard worker sampled the foreground window")

    def forbidden_sequence():
        raise AssertionError("frozen clipboard worker polled Windows clipboard state")

    monkeypatch.setattr(windows_clipboard, "clipboard_sequence_number", forbidden_sequence)
    monitor = ClipboardMonitor(source_window, capture_available=False)
    monitor.set_enabled(True)
    stop_event = threading.Event()
    stop_event.set()
    health = _Health()

    monitor.run(stop_event, health=health)

    assert monitor._enabled is False
    assert source_calls == 0
    assert health.succeeded_calls == 1
    assert health.paused == [True]


def test_dormant_monitor_implementation_remains_testable_for_future_work() -> None:
    monitor = ClipboardMonitor(lambda: None)

    monitor.set_enabled(True)

    assert monitor._enabled is True


def test_settings_ui_renders_clipboard_as_temporarily_unavailable() -> None:
    source = (
        ROOT / "worktrace/webview_ui/js/settings_presentation.js"
    ).read_text(encoding="utf-8")

    assert "status.clipboard_capture_supported === true" in source
    assert "captureToggle.disabled = !clipboardCaptureSupported(status)" in source
    assert '"暂未开放"' in source
