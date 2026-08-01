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
        if self.calls[:-1]:
            self.window = _Window()
        return self.window


@dataclass
class _PageAdapter:
    business_url: str = "https://work.fangdalaw.com/Works/WorkHourList?picker=day"
    login_url: str = "https://work.fangdalaw.com/Login?returnUrl=%2FWorks%2FWorkHourList%3Fpicker%3Dday"

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

    def check_login_page_ready(self, _window, callback):
        callback({"ready": True})


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
    assert webview.calls[0][0][1] == _PageAdapter().login_url


def test_login_readiness_retries_are_bounded_and_end_in_stable_failure():
    scheduled = []
    statuses = []

    class NeverReadyAdapter(_PageAdapter):
        def __init__(self):
            self.checks = 0

        def check_login_page_ready(self, _window, callback):
            self.checks += 1
            callback({"ready": False})

    adapter = NeverReadyAdapter()
    webview = _WebView()
    controller = FDWorkWindowController(
        webview,
        page_adapter=adapter,
        schedule=lambda callback: callback(),
        schedule_after=lambda delay, callback: scheduled.append((delay, callback)),
        status_callback=statuses.append,
        login_readiness_attempts=3,
        login_readiness_interval_seconds=0.25,
    )
    controller.open_entry(_draft())
    webview.window.events.loaded.fire()
    while scheduled:
        delay, callback = scheduled.pop(0)
        assert delay == 0.25
        callback()

    assert adapter.checks == 3
    assert statuses[-1] == "login_page_load_failed"


def test_old_login_readiness_callback_cannot_overwrite_new_navigation_success():
    callbacks = []
    statuses = []

    class DeferredAdapter(_PageAdapter):
        def check_login_page_ready(self, _window, callback):
            callbacks.append(callback)

    webview = _WebView()
    controller = FDWorkWindowController(
        webview,
        page_adapter=DeferredAdapter(),
        schedule=lambda callback: callback(),
        schedule_after=lambda _delay, callback: callback(),
        status_callback=statuses.append,
    )
    controller.open_entry(_draft())
    webview.window.events.loaded.fire()
    assert len(callbacks) == 1

    webview.window.url = _PageAdapter().business_url
    webview.window.events.loaded.fire()
    assert statuses[-1] == "filled"
    callbacks[0]({"ready": False})

    assert statuses[-1] == "filled"


@pytest.mark.parametrize("invalidate", ["disable", "close", "shutdown"])
def test_login_readiness_callback_is_invalidated_by_terminal_window_actions(invalidate):
    callbacks = []
    statuses = []

    class DeferredAdapter(_PageAdapter):
        def check_login_page_ready(self, _window, callback):
            callbacks.append(callback)

    webview = _WebView()
    controller = FDWorkWindowController(
        webview,
        page_adapter=DeferredAdapter(),
        schedule=lambda callback: callback(),
        status_callback=statuses.append,
    )
    controller.open_entry(_draft())
    webview.window.events.loaded.fire()
    assert len(callbacks) == 1

    if invalidate == "close":
        webview.window.events.closing.fire()
    else:
        getattr(controller, invalidate)()
    before = list(statuses)
    callbacks[0]({"ready": False})

    assert statuses == before


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


def test_reopen_reprocesses_current_page_without_waiting_for_new_loaded_event():
    webview = _WebView()
    controller = FDWorkWindowController(
        webview,
        page_adapter=_PageAdapter(),
        schedule=lambda callback: callback(),
    )
    controller.open_entry(_draft("CASE-OLD"))
    webview.window.url = _PageAdapter().business_url
    webview.window.events.loaded.fire()
    assert webview.window.last_draft.case_number == "CASE-OLD"

    assert webview.window.events.closing.fire() == [False]
    controller.open_entry(_draft("CASE-NEW"))

    assert len(webview.calls) == 1
    assert webview.window.last_draft.case_number == "CASE-NEW"


def test_reopen_invalidates_a_queued_hide_from_the_previous_close():
    queued = []
    webview = _WebView()
    controller = FDWorkWindowController(
        webview,
        page_adapter=_PageAdapter(),
        schedule=queued.append,
    )
    controller.open_entry(_draft("CASE-OLD"))
    assert webview.window.events.closing.fire() == [False]
    assert len(queued) == 1

    controller.open_entry(_draft("CASE-NEW"))
    assert len(queued) == 2
    queued[0]()

    assert webview.window.hidden == 0


def test_disable_clears_pending_draft_destroys_window_and_allows_reopen():
    webview = _WebView()
    controller = FDWorkWindowController(webview, page_adapter=_PageAdapter())
    controller.open_entry(_draft("CASE-OLD"))
    old_window = webview.window

    controller.disable()
    controller.disable()

    assert old_window.destroyed == 1
    old_window.events.closed.fire()
    controller.open_entry(_draft("CASE-NEW"))
    assert len(webview.calls) == 2
    assert webview.window is not old_window
    webview.window.url = _PageAdapter().business_url
    webview.window.events.loaded.fire()
    assert webview.window.last_draft.case_number == "CASE-NEW"


def test_shutdown_is_permanent_even_after_disable():
    webview = _WebView()
    controller = FDWorkWindowController(webview, page_adapter=_PageAdapter())
    controller.open_entry(_draft())
    controller.disable()
    controller.shutdown()

    assert controller.open_entry(_draft()) == {
        "ok": False,
        "error": "window_unavailable",
    }
    assert len(webview.calls) == 1
