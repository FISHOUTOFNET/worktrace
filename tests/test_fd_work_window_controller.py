from __future__ import annotations

from dataclasses import dataclass
import threading

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.page_adapter import FDWorkPageType
from worktrace.integrations.fd_work.window_controller import FDWorkWindowController


pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.parallel_safe,
]


class _Event:
    def __init__(self) -> None:
        self.handlers = []
        self.completed = False

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        self.completed = True
        return [handler() for handler in list(self.handlers)]

    def is_set(self):
        return self.completed


class _Window:
    def __init__(self, url: str) -> None:
        self.events = type(
            "Events",
            (),
            {"loaded": _Event(), "closing": _Event(), "closed": _Event()},
        )()
        self.url = url
        self.shown = 0
        self.hidden = 0
        self.restored = 0
        self.focused = 0
        self.destroyed = 0
        self.loaded_urls = []

    def get_current_url(self):
        return self.url

    def show(self):
        self.shown += 1

    def hide(self):
        self.hidden += 1

    def restore(self):
        self.restored += 1

    def focus(self):
        self.focused += 1

    def destroy(self):
        self.destroyed += 1

    def load_url(self, url):
        self.loaded_urls.append(url)


class _WebView:
    def __init__(self, business_url: str) -> None:
        self.calls = []
        self.business_url = business_url
        self.window = None

    def create_window(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.window = _Window(self.business_url)
        return self.window


@dataclass
class _PageAdapter:
    business_url: str = "https://work.fangdalaw.com/Works/WorkHourList?picker=day"
    login_url: str = "https://work.fangdalaw.com/Login?returnUrl=%2FWorks%2FWorkHourList%3Fpicker%3Dday"

    def __post_init__(self):
        self.fill_calls = []
        self.search_calls = []
        self.login_callbacks = []

    def detect_page(self, url):
        if "/login" in url.lower():
            return FDWorkPageType.LOGIN
        if "WorkHourList" in url:
            return FDWorkPageType.WORK_HOUR_LIST
        return FDWorkPageType.UNKNOWN

    def navigation_allowed(self, url):
        return url.startswith("https://work.fangdalaw.com/")

    def fill_entry(self, window, draft):
        self.fill_calls.append((window, draft))
        return {"ok": True, "status": "filled"}

    def search_cases(self, window, query):
        self.search_calls.append((window, query))
        return {"ok": True, "labels": ["CASE A"]}

    def check_login_page_ready(self, _window, callback):
        self.login_callbacks.append(callback)
        callback({"ready": True})

    def check_work_hour_page_ready(self, _window, callback):
        callback({"ready": True})


def _draft(label="CASE A"):
    return FDWorkEntryDraft("2026-08-01", label, "1.4", "Narrative")


def _controller(
    *,
    queued=None,
    delayed=None,
    statuses=None,
    adapter=None,
    **controller_kwargs,
):
    adapter = adapter or _PageAdapter()
    webview = _WebView(adapter.business_url)
    controller = FDWorkWindowController(
        webview,
        page_adapter=adapter,
        schedule=(queued.append if queued is not None else lambda callback: callback()),
        schedule_after=(
            (lambda delay, callback: delayed.append((delay, callback)))
            if delayed is not None else lambda _delay, _callback: None
        ),
        status_callback=(statuses.append if statuses is not None else None),
        **controller_kwargs,
    )
    return controller, webview, adapter


def test_prepare_is_lazy_singleton_and_creates_hidden_business_window_without_api():
    controller, webview, adapter = _controller()
    assert webview.calls == []

    controller.prepare_session(show_login_if_required=True)
    controller.prepare_session(show_login_if_required=True)

    assert len(webview.calls) == 1
    args, kwargs = webview.calls[0]
    assert args[1] == adapter.business_url
    assert kwargs["js_api"] is None
    assert kwargs["hidden"] is True
    assert kwargs["focus"] is False
    assert kwargs["resizable"] is True


def test_create_recovers_when_loaded_completed_before_handler_binding():
    queued = []
    adapter = _PageAdapter()

    class AlreadyLoadedWebView(_WebView):
        def create_window(self, *args, **kwargs):
            window = super().create_window(*args, **kwargs)
            window.events.loaded.completed = True
            return window

    webview = AlreadyLoadedWebView(adapter.business_url)
    controller = FDWorkWindowController(
        webview,
        page_adapter=adapter,
        schedule=queued.append,
        schedule_after=lambda _delay, _callback: None,
    )

    controller.prepare_session()
    assert len(queued) == 1
    while queued:
        queued.pop(0)()

    assert controller.get_status()["session_state"] == "ready"
    assert webview.window.hidden == 1


def test_valid_session_becomes_ready_and_stays_hidden():
    statuses = []
    controller, webview, _adapter = _controller(statuses=statuses)
    controller.prepare_session()

    webview.window.events.loaded.fire()

    assert controller.get_status()["session_state"] == "ready"
    assert controller.get_status()["operation"] == "none"
    assert webview.window.hidden == 1
    assert webview.window.shown == 0
    assert statuses[-1]["ready"] is True


def test_business_url_waits_for_form_readiness_before_claiming_ready():
    callbacks = []

    class DeferredWorkPageAdapter(_PageAdapter):
        def check_work_hour_page_ready(self, _window, callback):
            callbacks.append(callback)

    queued = []
    controller, webview, _adapter = _controller(
        queued=queued,
        adapter=DeferredWorkPageAdapter(),
    )
    controller.prepare_session()
    webview.window.events.loaded.fire()
    queued.pop(0)()

    assert len(callbacks) == 1
    assert controller.get_status()["session_state"] == "starting"
    assert webview.window.hidden == 0


def test_business_url_with_rendered_login_contract_becomes_login_required():
    class RenderedLoginPageAdapter(_PageAdapter):
        def check_work_hour_page_ready(self, _window, callback):
            callback({"ready": False, "login_ready": True})

    queued = []
    controller, webview, _adapter = _controller(
        queued=queued,
        adapter=RenderedLoginPageAdapter(),
    )
    controller.prepare_session(show_login_if_required=True)
    webview.window.events.loaded.fire()
    queued.pop(0)()

    assert controller.get_status()["session_state"] == "login_required"
    assert controller.get_status()["login_required"] is True
    assert webview.window.shown == 1
    assert webview.window.focused == 1


def test_business_url_with_in_document_login_navigation_becomes_login_required():
    class RedirectedLoginPageAdapter(_PageAdapter):
        def check_work_hour_page_ready(self, _window, callback):
            callback({"ready": False, "login_navigation": True})

    queued = []
    controller, webview, _adapter = _controller(
        queued=queued,
        adapter=RedirectedLoginPageAdapter(),
    )
    controller.prepare_session(show_login_if_required=True)
    webview.window.events.loaded.fire()
    queued.pop(0)()

    assert controller.get_status()["session_state"] == "login_required"
    assert webview.window.shown == 1


def test_unready_business_page_gets_one_hidden_generation_safe_reload():
    class UnreadyPageAdapter(_PageAdapter):
        def check_work_hour_page_ready(self, _window, callback):
            callback({"ready": False})

    queued = []
    controller, webview, adapter = _controller(
        queued=queued,
        adapter=UnreadyPageAdapter(),
        login_readiness_attempts=1,
    )
    controller.prepare_session()
    webview.window.events.loaded.fire()
    queued.pop(0)()

    assert webview.window.loaded_urls == [adapter.business_url]
    assert controller.get_status()["session_state"] == "starting"
    assert controller.get_status()["error_code"] is None
    assert webview.window.shown == 0

    webview.window.events.loaded.fire()
    queued.pop(0)()
    assert webview.window.loaded_urls == [adapter.business_url]
    assert controller.get_status()["error_code"] == "page_contract_changed"


def test_login_page_is_shown_and_close_only_hides_while_login_remains_required():
    queued = []
    controller, webview, _adapter = _controller(queued=queued)
    controller.prepare_session(show_login_if_required=True)
    webview.window.url = "https://work.fangdalaw.com/login"
    webview.window.events.loaded.fire()
    queued.pop(0)()

    assert controller.get_status()["session_state"] == "login_required"
    assert controller.get_status()["login_required"] is True
    assert webview.window.shown == 1
    assert webview.window.focused == 1

    assert webview.window.events.closing.fire() == [False]
    queued.pop(0)()
    assert webview.window.hidden == 1
    assert controller.get_status()["session_state"] == "login_required"


def test_login_success_without_pending_fill_hides_same_window():
    queued = []
    controller, webview, _adapter = _controller(queued=queued)
    controller.prepare_session()
    webview.window.url = "https://work.fangdalaw.com/login"
    webview.window.events.loaded.fire()
    queued.pop(0)()
    assert controller.get_status()["session_state"] == "login_required"

    webview.window.url = _PageAdapter().business_url
    webview.window.events.loaded.fire()
    queued.pop(0)()

    assert controller.get_status()["session_state"] == "ready"
    assert webview.window.hidden == 1


def test_pending_fill_continues_after_login_and_shows_review():
    queued = []
    controller, webview, adapter = _controller(queued=queued)
    controller.prepare_session()
    webview.window.url = "https://work.fangdalaw.com/login"
    webview.window.events.loaded.fire()
    queued.pop(0)()
    controller.open_entry(_draft())

    webview.window.url = adapter.business_url
    webview.window.events.loaded.fire()
    queued.pop(0)()

    assert [call[1] for call in adapter.fill_calls] == [_draft()]
    assert controller.get_status()["session_state"] == "ready"
    assert controller.get_status()["operation"] == "none"
    assert webview.window.shown >= 2


def test_search_and_fill_share_one_operation_and_fill_invalidates_search_result():
    search_started = threading.Event()
    release_search = threading.Event()
    queued = []

    class BlockingAdapter(_PageAdapter):
        def search_cases(self, window, query):
            search_started.set()
            assert release_search.wait(timeout=2)
            return {"ok": True, "labels": ["OLD"]}

    adapter = BlockingAdapter()
    controller, webview, _adapter = _controller(queued=queued, adapter=adapter)
    controller.prepare_session()
    webview.window.events.loaded.fire()
    queued.pop(0)()
    outcome = {}
    thread = threading.Thread(
        target=lambda: outcome.setdefault("result", controller.search_cases("old"))
    )
    thread.start()
    assert search_started.wait(timeout=2)

    controller.open_entry(_draft("NEW"))
    release_search.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert outcome["result"] == {"ok": False, "error": "fd_work_busy"}

    while queued:
        queued.pop(0)()
    assert [call[1].case_number for call in adapter.fill_calls] == ["NEW"]


def test_search_is_busy_while_filled_entry_waits_for_user_review():
    queued = []
    controller, webview, _adapter = _controller(queued=queued)
    controller.prepare_session()
    webview.window.events.loaded.fire()
    queued.pop(0)()
    controller.open_entry(_draft())
    queued.pop(0)()

    assert controller.search_cases("ca") == {"ok": False, "error": "fd_work_busy", "status": controller.get_status()}


def test_navigation_generation_invalidates_old_login_callback():
    callbacks = []

    class DeferredAdapter(_PageAdapter):
        def check_login_page_ready(self, _window, callback):
            callbacks.append(callback)

    queued = []
    controller, webview, adapter = _controller(queued=queued, adapter=DeferredAdapter())
    controller.prepare_session()
    webview.window.url = "https://work.fangdalaw.com/login"
    webview.window.events.loaded.fire()
    queued.pop(0)()
    assert len(callbacks) == 1

    webview.window.url = adapter.business_url
    webview.window.events.loaded.fire()
    queued.pop(0)()
    callbacks[0]({"ready": True})

    assert controller.get_status()["session_state"] == "ready"


def test_login_readiness_callback_has_a_fixed_timeout_and_bounded_attempts():
    callbacks = []

    class SilentAdapter(_PageAdapter):
        def check_login_page_ready(self, _window, callback):
            callbacks.append(callback)

    queued = []
    delayed = []
    controller, webview, _adapter = _controller(
        queued=queued,
        delayed=delayed,
        adapter=SilentAdapter(),
    )
    controller.prepare_session()
    webview.window.url = "https://work.fangdalaw.com/login"
    webview.window.events.loaded.fire()
    queued.pop(0)()

    scheduled_delays = []
    while delayed:
        assert len(delayed) == 1
        _delay, callback = delayed.pop(0)
        assert _delay > 0
        scheduled_delays.append(_delay)
        callback()

    assert len(callbacks) == 5
    assert len(scheduled_delays) == 9
    assert delayed == []
    assert controller.get_status()["session_state"] == "login_required"
    assert controller.get_status()["error_code"] == "login_required"


def test_explicitly_unready_login_contract_fails_closed_after_bounded_attempts():
    class UnreadyAdapter(_PageAdapter):
        def check_login_page_ready(self, _window, callback):
            callback({"ready": False})

    queued = []
    delayed = []
    controller, webview, _adapter = _controller(
        queued=queued,
        delayed=delayed,
        adapter=UnreadyAdapter(),
        login_readiness_attempts=2,
    )
    controller.prepare_session()
    webview.window.url = "https://work.fangdalaw.com/login"
    webview.window.events.loaded.fire()
    queued.pop(0)()

    while delayed:
        _delay, callback = delayed.pop(0)
        callback()

    assert controller.get_status()["session_state"] == "error"
    assert controller.get_status()["error_code"] == "session_start_failed"


def test_disable_destroys_window_allows_reenable_and_shutdown_is_permanent():
    controller, webview, _adapter = _controller()
    controller.prepare_session()
    first = webview.window
    controller.disable()
    controller.disable()
    assert first.destroyed == 1

    controller.prepare_session()
    assert len(webview.calls) == 2
    second = webview.window
    controller.shutdown()
    controller.shutdown()
    assert second.destroyed == 1
    assert controller.prepare_session() == {
        "ok": False,
        "error": "window_unavailable",
        "status": controller.get_status(),
    }


def test_renderer_failure_invalidates_window_and_reports_stable_error():
    controller, webview, _adapter = _controller()
    controller.prepare_session()
    window = webview.window

    controller.mark_renderer_unavailable()

    assert window.destroyed == 1
    assert controller.get_status()["session_state"] == "error"
    assert controller.get_status()["error_code"] == "renderer_unavailable"
    assert controller.prepare_session()["error"] == "renderer_unavailable"
