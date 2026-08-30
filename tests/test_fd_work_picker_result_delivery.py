from __future__ import annotations

import threading

import pytest

from worktrace.integrations.fd_work.main_window_sink import FDWorkMainWindowSink


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Loaded:
    def is_set(self): return True


class _Events:
    loaded = _Loaded()


class _RetryWindow:
    def __init__(self) -> None:
        self.events = _Events()
        self.picker_attempts = 0
        self.acked = threading.Event()

    def evaluate_js(self, script):
        if "receiveFDWorkCasePickerResult" not in script:
            return None
        self.picker_attempts += 1
        if self.picker_attempts == 1:
            raise RuntimeError("transient main WebView delivery failure")
        self.acked.set()
        return True


def test_terminal_picker_result_is_retained_until_main_webview_ack() -> None:
    sink = FDWorkMainWindowSink()
    window = _RetryWindow()
    sink.bind_window(window)
    sink.mark_ready()

    sink.picker_result({"ok": True, "request_id": "drawer", "selection_token": "token"})
    assert window.picker_attempts == 1

    sink.status_changed({"operation": "none", "session_state": "ready"})

    assert window.picker_attempts == 2
    assert window.acked.is_set()


def test_async_terminal_picker_result_retries_transient_failure_without_blocking_caller() -> None:
    sink = FDWorkMainWindowSink(deliver_asynchronously=True)
    window = _RetryWindow()
    sink.bind_window(window)
    sink.mark_ready()

    sink.picker_result({"ok": False, "request_id": "drawer", "error": "picker_canceled"})

    assert window.acked.wait(timeout=1.0)
    assert window.picker_attempts == 2
