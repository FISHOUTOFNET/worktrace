from __future__ import annotations

from dataclasses import dataclass

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.page_adapter import FDWorkPageType
from worktrace.integrations.fd_work.window_controller import FDWorkWindowController


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Event:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        return [handler() for handler in list(self.handlers)]


class _Window:
    def __init__(self) -> None:
        self.events = type(
            "Events",
            (),
            {"loaded": _Event(), "closing": _Event(), "closed": _Event()},
        )()
        self.url = "https://work.fangdalaw.com/login"
        self.shown = 0
        self.hidden = 0
        self.restored = 0
        self.destroyed = 0

    def get_current_url(self):
        return self.url

    def show(self):
        self.shown += 1

    def hide(self):
        self.hidden += 1

    def restore(self):
        self.restored += 1

    def destroy(self):
        self.destroyed += 1


class _WebView:
    def __init__(self) -> None:
        self.calls = []
        self.window = _Window()

    def create_window(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.window


@dataclass
class _PageAdapter:
    business_url: str = "https://work.fangdalaw.com/Works/WorkHourList?picker=day"

    def detect_page(self, url):
        if "/login" in url.lower():
            return FDWorkPageType.LOGIN
        if "WorkHourList" in url:
            return FDWorkPageType.WORK_HOUR_LIST
        return FDWorkPageType.UNKNOWN

    def navigation_allowed(self, url):
        return url.startswith("https://work.fangdalaw.com/")

    def fill_entry(self, window, draft):
        window.last_draft = draft
        return {"ok": True, "status": "filled"}


def _draft(label="CASE-001"):
    return FDWorkEntryDraft("2026-07-31", label, "1.4", "Narrative")


def test_window_is_lazy_singleton_and_has_no_js_api():
    webview = _WebView()
    controller = FDWorkWindowController(webview, page_adapter=_PageAdapter())
    assert webview.calls == []

    controller.open_entry(_draft())
    controller.open_entry(_draft())

    assert len(webview.calls) == 1
    assert webview.calls[0][1]["js_api"] is None


def test_new_request_replaces_pending_draft_and_login_never_injects():
    webview = _WebView()
    controller = FDWorkWindowController(webview, page_adapter=_PageAdapter())
    controller.open_entry(_draft("CASE-OLD"))
    controller.open_entry(_draft("CASE-NEW"))

    webview.window.events.loaded.fire()
    assert not hasattr(webview.window, "last_draft")

    webview.window.url = _PageAdapter().business_url
    webview.window.events.loaded.fire()
    assert webview.window.last_draft.case_number == "CASE-NEW"


def test_unknown_page_does_not_receive_draft():
    webview = _WebView()
    controller = FDWorkWindowController(webview, page_adapter=_PageAdapter())
    controller.open_entry(_draft())
    webview.window.url = "https://work.fangdalaw.com/Works/Other"

    webview.window.events.loaded.fire()

    assert not hasattr(webview.window, "last_draft")


def test_close_hides_reusable_window_and_shutdown_destroys_idempotently():
    queued = []
    webview = _WebView()
    controller = FDWorkWindowController(
        webview,
        page_adapter=_PageAdapter(),
        schedule=queued.append,
    )
    controller.open_entry(_draft())

    assert webview.window.events.closing.fire() == [False]
    assert webview.window.hidden == 0
    queued.pop()()
    assert webview.window.hidden == 1

    controller.open_entry(_draft())
    assert len(webview.calls) == 1
    assert webview.window.shown == 1
    assert webview.window.restored == 1

    controller.shutdown()
    controller.shutdown()
    assert webview.window.destroyed == 1
