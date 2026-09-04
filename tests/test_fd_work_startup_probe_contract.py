from __future__ import annotations

import pytest

from worktrace.integrations.fd_work.window_controller import FDWorkWindowController
from worktrace.integrations.fd_work.window_executor import FDWorkWindowCommandError

from tests.test_fd_work_window_controller import _PageAdapter, _WebView

pytestmark = [pytest.mark.integration, pytest.mark.collector_runtime, pytest.mark.contract, pytest.mark.serial]


def _controller(*, delayed: list[tuple[float, object]]):
    adapter = _PageAdapter()
    webview = _WebView(adapter.business_url)
    controller = FDWorkWindowController(
        webview,
        page_adapter=adapter,
        schedule=lambda callback: callback(),
        schedule_after=lambda delay, callback: delayed.append((delay, callback)),
    )
    controller.on_renderer_initialized("edgechromium")
    return controller, webview


def test_renderer_ready_does_not_probe_before_loaded_generation():
    delayed = []
    controller, webview = _controller(delayed=delayed)

    result = controller.prepare_window_before_start(False)

    assert result["ok"] is True
    assert delayed == []
    assert controller.get_status()["session_state"] == "probing"
    webview.window.events.loaded.fire()
    assert controller.get_status()["session_state"] == "ready"


def test_executor_stall_is_not_reported_as_navigation_blocked(monkeypatch):
    delayed = []
    controller, webview = _controller(delayed=delayed)
    controller.prepare_window_before_start(False)

    class BrokenWindow:
        def get_current_url(self):
  raise FDWorkWindowCommandError("executor_stalled")

    monkeypatch.setattr(controller, "_executor_window", lambda *_args: BrokenWindow())
    webview.window.events.loaded.fire()

    status = controller.get_status()
    assert status["session_state"] == "error"
    assert status["error_code"] == "window_executor_stalled"


def test_real_disallowed_url_remains_navigation_blocked():
    delayed = []
    controller, webview = _controller(delayed=delayed)
    controller.prepare_window_before_start(False)
    webview.window.url = "https://example.com/not-fd-work"

    webview.window.events.loaded.fire()

    status = controller.get_status()
    assert status["session_state"] == "error"
    assert status["error_code"] == "navigation_blocked"
