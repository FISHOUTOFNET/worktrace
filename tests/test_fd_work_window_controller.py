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
            {
                "before_load": _Event(),
                "loaded": _Event(),
                "closing": _Event(),
                "closed": _Event(),
            },
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
    renderer_initialized=True,
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
    if renderer_initialized:
        controller.on_renderer_initialized("edgechromium")
    return controller, webview, adapter


def _run_delayed(delayed, expected_delay):
    for index, (delay, callback) in enumerate(delayed):
        if delay == expected_delay:
            delayed.pop(index)
            callback()
            return
    raise AssertionError(f"no callback scheduled for {expected_delay}")


def test_startup_prepare_creates_hidden_singleton_and_binds_before_gui_start():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
    )

    first = controller.prepare_window_before_start(show_login_if_required=True)
    second = controller.prepare_window_before_start(show_login_if_required=True)

    assert first["ok"] is True
    assert second["ok"] is True
    assert len(webview.calls) == 1
    assert webview.calls[0][1]["hidden"] is True
    assert webview.calls[0][1]["focus"] is False
    assert len(webview.window.events.before_load.handlers) == 1
    assert len(webview.window.events.loaded.handlers) == 1
    assert len(webview.window.events.closing.handlers) == 1
    assert len(webview.window.events.closed.handlers) == 1
    assert delayed == []


def test_renderer_initialization_arms_initial_load_watchdog_only_after_start():
    delayed = []
    controller, _webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.prepare_window_before_start()
    assert delayed == []

    controller.on_renderer_initialized("edgechromium")

    assert sorted(delay for delay, _callback in delayed) == [5.0, 30.0]


def test_missing_loaded_watchdog_shows_and_probes_login_page():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.prepare_window_before_start()
    webview.window.url = "https://work.fangdalaw.com/login"
    controller.on_renderer_initialized("edgechromium")

    _run_delayed(delayed, 5.0)

    assert controller.get_status()["session_state"] == "login_required"
    assert webview.window.shown >= 1
    assert webview.window.restored >= 1
    assert webview.window.focused >= 1
    assert len(webview.calls) == 1


def test_missing_loaded_watchdog_probes_ready_page_and_hides_without_fill():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.prepare_window_before_start()
    controller.on_renderer_initialized("edgechromium")

    _run_delayed(delayed, 5.0)

    assert controller.get_status()["session_state"] == "ready"
    assert webview.window.shown == 1
    assert webview.window.hidden == 1
    assert len(webview.calls) == 1


def test_unrecognized_initial_probe_has_hard_timeout_instead_of_permanent_starting():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.prepare_window_before_start()
    webview.window.url = "https://work.fangdalaw.com/loading"
    controller.on_renderer_initialized("edgechromium")

    _run_delayed(delayed, 5.0)
    assert controller.get_status()["session_state"] == "starting"
    _run_delayed(delayed, 30.0)

    assert controller.get_status()["session_state"] == "error"
    assert controller.get_status()["error_code"] == "session_start_timeout"
    assert controller.get_status()["operation"] == "none"
    assert webview.window.shown >= 1


def test_prepare_while_starting_shows_same_window_probes_and_reuses_watchdog():
    delayed = []

    class UnknownAdapter(_PageAdapter):
        def detect_page(self, _url):
            return FDWorkPageType.UNKNOWN

    controller, webview, _adapter = _controller(
        delayed=delayed,
        adapter=UnknownAdapter(),
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.prepare_window_before_start()
    controller.on_renderer_initialized("edgechromium")

    result = controller.prepare_session(show_login_if_required=True)

    assert result["ok"] is True
    assert webview.window.shown == 1
    assert webview.window.restored == 1
    assert webview.window.focused == 1
    assert len(webview.calls) == 1
    assert sorted(delay for delay, _callback in delayed) == [5.0, 30.0]


def test_prepare_reports_session_starting_while_create_window_has_not_returned():
    create_entered = threading.Event()
    release_create = threading.Event()
    adapter = _PageAdapter()

    class BlockingWebView(_WebView):
        def create_window(self, *args, **kwargs):
            create_entered.set()
            assert release_create.wait(timeout=2)
            return super().create_window(*args, **kwargs)

    webview = BlockingWebView(adapter.business_url)
    controller = FDWorkWindowController(webview, page_adapter=adapter)
    thread = threading.Thread(target=controller.prepare_session)
    thread.start()
    assert create_entered.wait(timeout=2)

    result = controller.prepare_session(show_login_if_required=True)
    release_create.set()
    thread.join(timeout=2)

    assert result["ok"] is False
    assert result["error"] == "session_starting"
    assert not thread.is_alive()


def test_late_loaded_recovers_from_start_timeout_on_same_window():
    delayed = []
    queued = []
    controller, webview, adapter = _controller(
        delayed=delayed,
        queued=queued,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.prepare_window_before_start()
    webview.window.url = "https://work.fangdalaw.com/loading"
    controller.on_renderer_initialized("edgechromium")
    _run_delayed(delayed, 30.0)
    assert controller.get_status()["error_code"] == "session_start_timeout"

    webview.window.url = adapter.business_url
    webview.window.events.loaded.fire()
    queued.pop(0)()
    delayed[:] = [
        (delay, callback)
        for delay, callback in delayed
        if delay not in {5.0, 30.0}
    ]

    assert controller.get_status()["session_state"] == "ready"
    assert controller.get_status()["error_code"] is None


def test_disable_and_shutdown_invalidate_old_start_watchdogs():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.prepare_window_before_start()
    first = webview.window
    controller.on_renderer_initialized("edgechromium")
    callbacks = [callback for _delay, callback in delayed]
    controller.disable()
    for callback in callbacks:
        callback()
    assert controller.get_status()["session_state"] == "idle"
    assert first.shown == 0

    delayed.clear()
    controller.prepare_session()
    second = webview.window
    callbacks = [callback for _delay, callback in delayed]
    controller.shutdown()
    for callback in callbacks:
        callback()
    assert controller.get_status()["session_state"] == "shutdown"
    assert second.shown == 0


def test_reenabled_window_is_not_changed_by_old_generation_watchdog():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.prepare_window_before_start()
    controller.on_renderer_initialized("edgechromium")
    stale_callbacks = [callback for _delay, callback in delayed]
    controller.disable()
    delayed.clear()
    controller.prepare_session()
    second = webview.window
    for callback in stale_callbacks:
        callback()

    assert controller.get_status()["session_state"] == "starting"
    assert second.shown == 0


def test_dynamic_window_created_after_renderer_initialization_gets_watchdog():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    controller.on_renderer_initialized("edgechromium")

    controller.prepare_session(show_login_if_required=True)

    assert len(webview.calls) == 1
    assert sorted(delay for delay, _callback in delayed) == [5.0, 30.0]


def test_diagnostics_emit_only_whitelisted_lifecycle_metadata(caplog):
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        start_probe_delay_seconds=5.0,
        start_timeout_seconds=30.0,
    )
    with caplog.at_level("INFO"):
        controller.prepare_window_before_start()
        webview.window.events.before_load.fire()
        webview.window.url = "https://work.fangdalaw.com/login"
        controller.on_renderer_initialized("edgechromium")
        _run_delayed(delayed, 5.0)
        _run_delayed(delayed, 1.0)
        controller.disable()

    messages = [record.getMessage() for record in caplog.records]
    joined = "\n".join(messages)
    for event in (
        "fd_work_prepare_requested",
        "fd_work_create_reserved",
        "fd_work_create_begin",
        "fd_work_create_returned",
        "fd_work_handlers_bound",
        "fd_work_before_load",
        "fd_work_renderer_initialized",
        "fd_work_start_watchdog_armed",
        "fd_work_start_watchdog_probe",
        "fd_work_start_watchdog_visible",
        "fd_work_page_detected",
        "fd_work_login_required",
        "fd_work_login_watch_armed",
        "fd_work_login_watch_probe",
        "fd_work_ready",
        "fd_work_window_show",
        "fd_work_window_hide",
        "fd_work_window_destroy",
    ):
        assert event in joined
    assert "session_state=" in joined
    assert "operation=" in joined
    assert "navigation_generation=" in joined
    assert "operation_generation=" in joined
    assert "window_exists=" in joined
    assert "renderer=edgechromium" in joined
    assert "page_type=login" in joined
    assert "elapsed_ms=" in joined
    assert "https://" not in joined
    assert "password" not in joined.lower()
    assert "query" not in joined.lower()


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
    controller.on_renderer_initialized("edgechromium")
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


def test_slow_work_page_can_become_ready_after_thirty_seconds_without_reload():
    delayed = []

    class SlowWorkPageAdapter(_PageAdapter):
        attempts = 0

        def check_work_hour_page_ready(self, _window, callback):
            self.attempts += 1
            callback({"ready": self.attempts >= 31})

    adapter = SlowWorkPageAdapter()
    controller, webview, _adapter = _controller(
        delayed=delayed,
        adapter=adapter,
        work_readiness_attempts=35,
        work_readiness_interval_seconds=1.0,
    )
    controller.prepare_session()
    webview.window.events.loaded.fire()

    for _attempt in range(30):
        _run_delayed(delayed, 1.0)

    assert adapter.attempts == 31
    assert webview.window.loaded_urls == []
    assert controller.get_status()["session_state"] == "ready"
    assert webview.window.hidden == 1


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


def test_unready_business_page_gets_one_hidden_generation_safe_login_fallback():
    class UnreadyPageAdapter(_PageAdapter):
        def check_work_hour_page_ready(self, _window, callback):
            callback({"ready": False})

    queued = []
    controller, webview, adapter = _controller(
        queued=queued,
        adapter=UnreadyPageAdapter(),
        work_readiness_attempts=1,
    )
    controller.prepare_session()
    webview.window.events.loaded.fire()
    queued.pop(0)()

    assert webview.window.loaded_urls == [adapter.login_url]
    assert controller.get_status()["session_state"] == "starting"
    assert controller.get_status()["error_code"] is None
    assert webview.window.shown == 0

    webview.window.events.loaded.fire()
    queued.pop(0)()
    assert webview.window.loaded_urls == [adapter.login_url]
    assert controller.get_status()["error_code"] == "page_contract_changed"


def test_login_page_is_shown_and_user_close_allows_native_destroy():
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

    assert webview.window.events.closing.fire() == [True]
    assert queued == []
    assert webview.window.hidden == 0
    webview.window.events.closed.fire()
    assert controller.get_status()["session_state"] == "idle"


def test_user_close_calls_no_window_api_and_prepare_recreates_one_window():
    controller, webview, _adapter = _controller()
    controller.prepare_session()
    first = webview.window
    before = (first.shown, first.hidden, first.restored, first.focused, first.destroyed)

    assert first.events.closing.fire() == [True]
    after = (first.shown, first.hidden, first.restored, first.focused, first.destroyed)
    assert after == before
    first.events.closed.fire()
    assert controller.prepare_session()["ok"] is True
    assert len(webview.calls) == 2
    assert webview.window is not first


def test_stale_closed_callback_cannot_clear_recreated_window():
    controller, webview, _adapter = _controller()
    controller.prepare_session()
    first = webview.window
    first.events.closing.fire()
    first.events.closed.fire()
    controller.prepare_session()
    second = webview.window

    first.events.closed.fire()

    assert controller.get_status()["session_state"] == "starting"
    assert len(webview.calls) == 2
    assert webview.window is second


def test_fifty_user_close_recreate_cycles_keep_one_handler_per_window():
    controller, webview, _adapter = _controller()

    for _index in range(50):
        assert controller.prepare_session()["ok"] is True
        window = webview.window
        assert len(window.events.closing.handlers) == 1
        assert len(window.events.closed.handlers) == 1
        assert window.events.closing.fire() == [True]
        window.events.closed.fire()
        assert controller.get_status()["session_state"] == "idle"

    assert len(webview.calls) == 50


def test_user_close_invalidates_late_search_callback_without_waiting_for_it():
    started = threading.Event()
    release = threading.Event()

    class BlockingAdapter(_PageAdapter):
        def search_cases(self, window, query):
            started.set()
            assert release.wait(timeout=2)
            return {"ok": True, "labels": ["STALE"]}

    controller, webview, _adapter = _controller(adapter=BlockingAdapter())
    controller.prepare_session()
    webview.window.events.loaded.fire()
    outcome = {}
    worker = threading.Thread(
        target=lambda: outcome.setdefault("result", controller.search_cases("A"))
    )
    worker.start()
    assert started.wait(timeout=2)

    assert webview.window.events.closing.fire() == [True]
    webview.window.events.closed.fire()
    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert outcome["result"] == {"ok": False, "error": "lookup_superseded"}
    assert controller.get_status()["session_state"] == "idle"


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


def test_login_success_without_loaded_is_detected_by_login_transition_probe():
    queued = []
    delayed = []

    class LoginTransitionAdapter(_PageAdapter):
        work_page_ready = False

        def check_work_hour_page_ready(self, _window, callback):
            callback({"ready": self.work_page_ready})

    adapter = LoginTransitionAdapter()
    controller, webview, _adapter = _controller(
        queued=queued,
        delayed=delayed,
        adapter=adapter,
        login_transition_interval_seconds=1.0,
    )
    controller.prepare_session()
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()
    queued.pop(0)()
    assert controller.get_status()["session_state"] == "login_required"

    adapter.work_page_ready = True
    _run_delayed(delayed, 1.0)

    assert controller.get_status()["session_state"] == "ready"
    assert webview.window.hidden == 1


def test_stale_login_transition_probe_cannot_change_a_new_navigation():
    queued = []
    delayed = []

    class LoginTransitionAdapter(_PageAdapter):
        def check_work_hour_page_ready(self, _window, callback):
            callback({"ready": True})

    adapter = LoginTransitionAdapter()
    controller, webview, _adapter = _controller(
        queued=queued,
        delayed=delayed,
        adapter=adapter,
        login_transition_interval_seconds=1.0,
    )
    controller.prepare_session()
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()
    queued.pop(0)()
    old_generation = controller.get_status()["navigation_generation"]

    webview.window.events.loaded.fire()
    queued.pop(0)()
    assert controller.get_status()["navigation_generation"] > old_generation
    _run_delayed(delayed, 1.0)

    assert controller.get_status()["session_state"] == "login_required"
    assert webview.window.hidden == 0


def test_login_transition_probe_keeps_waiting_without_reload_or_error():
    queued = []
    delayed = []

    class WaitingAdapter(_PageAdapter):
        def check_work_hour_page_ready(self, _window, callback):
            callback({"ready": False, "login_ready": True})

    adapter = WaitingAdapter()
    controller, webview, _adapter = _controller(
        queued=queued,
        delayed=delayed,
        adapter=adapter,
        login_transition_interval_seconds=1.0,
    )
    controller.prepare_session()
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()
    queued.pop(0)()

    _run_delayed(delayed, 1.0)

    assert controller.get_status()["session_state"] == "login_required"
    assert webview.window.loaded_urls == []
    assert [delay for delay, _callback in delayed].count(1.0) == 1


def test_disable_invalidates_login_transition_probe():
    queued = []
    delayed = []
    adapter = _PageAdapter()
    controller, webview, _adapter = _controller(
        queued=queued,
        delayed=delayed,
        adapter=adapter,
        login_transition_interval_seconds=1.0,
    )
    controller.prepare_session()
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()
    queued.pop(0)()

    controller.disable()
    _run_delayed(delayed, 1.0)

    assert controller.get_status()["session_state"] == "idle"
    assert webview.window.hidden == 0


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
    assert outcome["result"] == {"ok": False, "error": "lookup_superseded"}

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
        login_readiness_attempts=5,
        login_readiness_interval_seconds=0.5,
        login_transition_interval_seconds=17.0,
    )
    controller.prepare_session()
    webview.window.url = "https://work.fangdalaw.com/login"
    webview.window.events.loaded.fire()
    queued.pop(0)()
    delayed[:] = [
        (delay, callback)
        for delay, callback in delayed
        if delay not in {5.0, 30.0}
    ]

    scheduled_delays = []
    while any(delay != 17.0 for delay, _callback in delayed):
        active = [
            (index, delay, callback)
            for index, (delay, callback) in enumerate(delayed)
            if delay != 17.0
        ]
        assert len(active) == 1
        index, _delay, callback = active[0]
        delayed.pop(index)
        assert _delay > 0
        scheduled_delays.append(_delay)
        callback()

    assert len(callbacks) == 5
    assert len(scheduled_delays) == 9
    assert [delay for delay, _callback in delayed] == [17.0]
    assert controller.get_status()["session_state"] == "login_required"
    assert controller.get_status()["error_code"] == "login_required"


def test_explicitly_unready_login_contract_remains_login_required_after_bound():
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
        login_transition_interval_seconds=17.0,
    )
    controller.prepare_session()
    webview.window.url = "https://work.fangdalaw.com/login"
    webview.window.events.loaded.fire()
    queued.pop(0)()

    while any(delay != 17.0 for delay, _callback in delayed):
        index = next(
            index
            for index, (delay, _callback) in enumerate(delayed)
            if delay != 17.0
        )
        _delay, callback = delayed.pop(index)
        callback()

    assert controller.get_status()["session_state"] == "login_required"
    assert controller.get_status()["error_code"] == "login_required"


def test_slow_login_dom_can_settle_after_thirty_seconds():
    delayed = []

    class SlowLoginAdapter(_PageAdapter):
        attempts = 0

        def check_login_page_ready(self, _window, callback):
            self.attempts += 1
            callback({"ready": self.attempts >= 31})

    adapter = SlowLoginAdapter()
    controller, webview, _adapter = _controller(
        delayed=delayed,
        adapter=adapter,
        login_transition_interval_seconds=17.0,
    )
    controller.prepare_session()
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()

    for _attempt in range(30):
        _run_delayed(delayed, 1.0)

    assert adapter.attempts == 31
    assert controller.get_status()["session_state"] == "login_required"
    assert [delay for delay, _callback in delayed].count(17.0) == 1


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
