from __future__ import annotations

from dataclasses import dataclass
import threading

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
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
        self.url = url


class _WebView:
    def __init__(self, business_url: str) -> None:
        self.calls = []
        self.business_url = business_url
        self.window = None
        self.windows = []

    def create_window(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.window = _Window(self.business_url)
        self.windows.append(self.window)
        return self.window


@dataclass
class _PageAdapter:
    business_url: str = "https://work.fangdalaw.com/Works/WorkHourList?picker=day"
    login_url: str = "https://work.fangdalaw.com/Login?returnUrl=%2FWorks%2FWorkHourList%3Fpicker%3Dday"

    def __post_init__(self):
        self.install_calls = []
        self.interactive_calls = []
        self.search_calls = []
        self.fill_calls = []
        self.install_result = {"ok": True, "version": 4}
        self.interactive_result = {
            "ok": True,
            "phase": "work_interactive",
            "document_visibility": "visible",
            "viewport_available": True,
            "input_exists": True,
            "input_interactive": True,
            "popup_exists": True,
            "popup_interactive": True,
        }
        self.search_result = {"ok": True, "labels": ["CASE A"]}
        self.fill_result = {"ok": True, "status": "filled"}
        self.deferred_probes = []

    def navigation_allowed(self, url):
        return str(url or "").startswith("https://work.fangdalaw.com/")

    def probe_page_phase(self, window, callback):
        url = window.get_current_url().lower()
        if "/logintoken" in url:
            callback({"phase": "login_confirmation"})
        elif "/login" in url:
            callback({"phase": "login_credentials"})
        elif "workhourlist" in url:
            callback({"phase": "work_shell"})
        elif "/unauthorized" in url:
            callback({"phase": "unauthorized"})
        else:
            callback({"phase": "unknown"})

    def install_adapter(self, window):
        self.install_calls.append(window)
        return dict(self.install_result)

    def check_work_interactive(self, window, timeout_seconds):
        self.interactive_calls.append((window, timeout_seconds))
        return dict(self.interactive_result)

    def search_cases(self, window, query, *, timeout_seconds):
        self.search_calls.append((window, query, timeout_seconds))
        return dict(self.search_result)

    def fill_entry(self, window, draft, *, timeout_seconds):
        self.fill_calls.append((window, draft, timeout_seconds))
        return dict(self.fill_result)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _draft(label="CASE A"):
    return FDWorkEntryDraft("2026-08-01", label, "1.4", "Narrative")


def _controller(
    *,
    queued=None,
    delayed=None,
    statuses=None,
    adapter=None,
    renderer_initialized=True,
    clock=None,
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
            if delayed is not None
            else lambda _delay, _callback: None
        ),
        status_callback=(statuses.append if statuses is not None else None),
        clock=clock or __import__("time").monotonic,
        **controller_kwargs,
    )
    if renderer_initialized:
        controller.on_renderer_initialized("edgechromium")
    return controller, webview, adapter


def _run_next(delayed, clock=None):
    assert delayed
    delay, callback = delayed.pop(0)
    if clock is not None:
        clock.advance(delay)
    callback()
    return delay


def test_passive_prestart_creates_one_hidden_api_free_window_and_binds_handlers():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed, renderer_initialized=False
    )

    first = controller.prepare_window_before_start(show_login_if_required=False)
    second = controller.prepare_window_before_start(show_login_if_required=False)

    assert first["ok"] is True and second["ok"] is True
    assert len(webview.calls) == 1
    args, kwargs = webview.calls[0]
    assert args[1].endswith("WorkHourList?picker=day")
    assert kwargs["hidden"] is True
    assert kwargs["focus"] is False
    assert kwargs["js_api"] is None
    assert webview.window.shown == 0
    assert len(webview.window.events.loaded.handlers) == 1
    assert len(webview.window.events.closing.handlers) == 1
    assert len(webview.window.events.closed.handlers) == 1
    assert delayed == []


def test_explicit_login_request_shows_new_window_immediately_without_os_focus():
    delayed = []
    controller, webview, _adapter = _controller(delayed=delayed)

    result = controller.prepare_session(show_login_if_required=True)

    assert result["ok"] is True
    assert webview.window.shown == 1
    assert webview.window.restored == 1
    assert webview.window.focused == 0
    assert all(delay <= 4.0 for delay, _callback in delayed)


def test_missing_loaded_event_uses_short_passive_fallback_and_can_reach_ready():
    delayed = []
    controller, webview, _adapter = _controller(
        delayed=delayed, renderer_initialized=False
    )
    controller.prepare_window_before_start(show_login_if_required=False)

    controller.on_renderer_initialized("edgechromium")
    delay = _run_next(delayed)

    assert delay <= 0.25
    assert controller.get_status()["session_state"] == "ready"
    assert controller.get_status()["page_phase"] == "work_shell"
    assert webview.window.hidden == 1


def test_passive_unknown_probe_has_one_short_deadline_and_returns_inconclusive():
    delayed = []
    clock = _Clock()
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        clock=clock,
        passive_probe_timeout_seconds=3.0,
        probe_interval_seconds=0.5,
    )
    controller.prepare_window_before_start(show_login_if_required=False)
    webview.window.url = "https://work.fangdalaw.com/loading"
    controller.on_renderer_initialized("edgechromium")

    while delayed:
        _run_next(delayed, clock)

    status = controller.get_status()
    assert clock.now <= 103.0
    assert status["session_state"] == "idle"
    assert status["error_code"] == "session_probe_inconclusive"
    assert status["page_phase"] == "unknown"
    assert webview.window.shown == 0


def test_explicit_unknown_probe_has_bounded_work_shell_timeout_and_stays_visible():
    delayed = []
    clock = _Clock()
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
        clock=clock,
        work_shell_timeout_seconds=2.0,
        probe_interval_seconds=0.5,
    )
    controller.prepare_session(show_login_if_required=True)
    webview.window.url = "https://work.fangdalaw.com/loading"
    controller.on_renderer_initialized("edgechromium")

    while delayed:
        _run_next(delayed, clock)

    status = controller.get_status()
    assert clock.now <= 102.0
    assert status["session_state"] == "error"
    assert status["error_code"] == "work_shell_timeout"
    assert webview.window.shown == 1


@pytest.mark.parametrize(
    ("path", "phase"),
    [
        ("Login", "login_credentials"),
        ("LoginToken", "login_confirmation"),
    ],
)
def test_login_phases_are_accepted_immediately_without_credentials_polling(path, phase):
    delayed = []
    controller, webview, _adapter = _controller(delayed=delayed)
    controller.prepare_session(show_login_if_required=True)
    webview.window.url = f"https://work.fangdalaw.com/{path}"

    webview.window.events.loaded.fire()

    status = controller.get_status()
    assert status["session_state"] == "login_required"
    assert status["page_phase"] == phase
    assert webview.window.shown == 1
    assert webview.window.hidden == 0


def test_login_navigation_to_work_shell_becomes_ready_on_loaded_without_polling():
    controller, webview, adapter = _controller()
    controller.prepare_session(show_login_if_required=True)
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()
    assert controller.get_status()["page_phase"] == "login_credentials"

    webview.window.url = adapter.business_url
    webview.window.events.loaded.fire()

    assert controller.get_status()["session_state"] == "ready"
    assert controller.get_status()["page_phase"] == "work_shell"
    assert webview.window.hidden == 1


def test_login_transition_fallback_is_bounded_and_recovers_without_loaded():
    delayed = []
    clock = _Clock()
    controller, webview, adapter = _controller(
        delayed=delayed,
        clock=clock,
        login_transition_interval_seconds=0.5,
        work_shell_timeout_seconds=2.0,
    )
    controller.prepare_session(show_login_if_required=True)
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()
    webview.window.url = adapter.business_url

    while delayed and controller.get_status()["session_state"] != "ready":
        _run_next(delayed, clock)

    assert controller.get_status()["session_state"] == "ready"
    assert webview.window.hidden == 1


def test_stale_navigation_probe_cannot_change_new_page():
    callbacks = []

    class DeferredAdapter(_PageAdapter):
        def probe_page_phase(self, _window, callback):
            callbacks.append(callback)

    adapter = DeferredAdapter()
    queued = []
    controller, webview, _adapter = _controller(queued=queued, adapter=adapter)
    controller.prepare_session(show_login_if_required=False)
    webview.window.events.loaded.fire()
    queued.pop(0)()
    first = callbacks.pop(0)

    webview.window.events.loaded.fire()
    queued.pop(0)()
    second = callbacks.pop(0)
    first({"phase": "login_credentials"})
    second({"phase": "work_shell"})

    assert controller.get_status()["session_state"] == "ready"
    assert controller.get_status()["page_phase"] == "work_shell"


def test_adapter_installs_once_per_navigation_and_mismatch_fails_clearly():
    controller, webview, adapter = _controller()
    controller.prepare_session(show_login_if_required=False)
    webview.window.events.loaded.fire()
    assert controller.search_cases("A")["ok"] is True
    assert controller.search_cases("B")["ok"] is True
    assert len(adapter.install_calls) == 1

    webview.window.events.loaded.fire()
    assert len(adapter.install_calls) == 2

    adapter.install_result = {"ok": False, "error": "adapter_injection_failed"}
    webview.window.events.loaded.fire()
    assert controller.get_status()["session_state"] == "error"
    assert controller.get_status()["error_code"] == "adapter_injection_failed"


def test_hidden_ready_search_uses_interactive_lease_then_rehides_without_focus():
    controller, webview, adapter = _controller()
    controller.prepare_session(show_login_if_required=False)
    webview.window.events.loaded.fire()
    hidden_before = webview.window.hidden

    result = controller.search_cases("A")

    assert result["ok"] is True
    assert result["labels"] == ["CASE A"]
    assert webview.window.shown == 1
    assert webview.window.restored == 1
    assert webview.window.focused == 0
    assert webview.window.hidden == hidden_before + 1
    assert len(adapter.interactive_calls) == 1
    assert len(adapter.search_calls) == 1
    assert adapter.interactive_calls[0][1] <= 3.0
    assert adapter.search_calls[0][2] <= 8.0
    assert controller.get_status()["page_phase"] == "work_shell"


@pytest.mark.parametrize(
    "error",
    [
        "case_input_missing",
        "case_input_not_interactive",
        "case_input_not_rendered",
        "case_aria_controls_missing",
        "case_popup_not_created",
        "case_popup_not_interactive",
    ],
)
def test_interactive_lease_preserves_specific_stage_error_and_rehides(error):
    adapter = _PageAdapter()
    adapter.interactive_result = {"ok": False, "error": error}
    controller, webview, _adapter = _controller(adapter=adapter)
    controller.prepare_session(show_login_if_required=False)
    webview.window.events.loaded.fire()

    result = controller.search_cases("A")

    assert result["error"] == error
    assert controller.get_status()["session_state"] == "ready"
    assert controller.get_status()["error_code"] == error
    assert webview.window.hidden == 2
    assert adapter.search_calls == []


def test_fill_uses_interactive_lease_and_success_keeps_review_visible():
    controller, webview, adapter = _controller()
    controller.prepare_session(show_login_if_required=False)
    webview.window.events.loaded.fire()

    assert controller.open_entry(_draft())["ok"] is True

    assert [call[1] for call in adapter.fill_calls] == [_draft()]
    assert len(adapter.interactive_calls) == 1
    assert webview.window.shown == 1
    assert webview.window.focused == 1
    assert controller.get_status()["session_state"] == "ready"
    assert controller.search_cases("A")["error"] == "fd_work_busy"


def test_fill_failure_keeps_window_visible_with_specific_error():
    adapter = _PageAdapter()
    adapter.fill_result = {"ok": False, "error": "case_results_stale"}
    controller, webview, _adapter = _controller(adapter=adapter)
    controller.prepare_session(show_login_if_required=False)
    webview.window.events.loaded.fire()

    controller.open_entry(_draft())

    assert webview.window.shown == 1
    assert controller.get_status()["error_code"] == "case_results_stale"
    assert controller.get_status()["ready"] is True


def test_user_close_during_lookup_supersedes_result_without_window_api_reentry():
    started = threading.Event()
    release = threading.Event()

    class BlockingAdapter(_PageAdapter):
        def search_cases(self, window, query, *, timeout_seconds):
            started.set()
            assert release.wait(timeout=2)
            return {"ok": True, "labels": ["STALE"]}

    controller, webview, _adapter = _controller(adapter=BlockingAdapter())
    controller.prepare_session(show_login_if_required=False)
    webview.window.events.loaded.fire()
    window = webview.window
    outcome = {}
    worker = threading.Thread(
        target=lambda: outcome.setdefault("result", controller.search_cases("A"))
    )
    worker.start()
    assert started.wait(timeout=2)
    before = (window.shown, window.hidden, window.restored, window.focused, window.destroyed)

    assert window.events.closing.fire() == [True]
    during = (window.shown, window.hidden, window.restored, window.focused, window.destroyed)
    assert during == before
    window.events.closed.fire()
    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert outcome["result"] == {"ok": False, "error": "lookup_superseded"}
    assert controller.get_status()["session_state"] == "idle"


def test_late_interactive_callback_after_close_cannot_rehide_or_reshow():
    entered = threading.Event()
    release = threading.Event()

    class BlockingLeaseAdapter(_PageAdapter):
        def check_work_interactive(self, window, timeout_seconds):
            entered.set()
            assert release.wait(timeout=2)
            return dict(self.interactive_result)

    controller, webview, _adapter = _controller(adapter=BlockingLeaseAdapter())
    controller.prepare_session(show_login_if_required=False)
    webview.window.events.loaded.fire()
    window = webview.window
    outcome = {}
    worker = threading.Thread(
        target=lambda: outcome.setdefault("result", controller.search_cases("A"))
    )
    worker.start()
    assert entered.wait(timeout=2)
    window.events.closing.fire()
    window.events.closed.fire()
    counts = (window.shown, window.hidden, window.restored, window.focused)
    release.set()
    worker.join(timeout=2)

    assert outcome["result"] == {"ok": False, "error": "lookup_superseded"}
    assert (window.shown, window.hidden, window.restored, window.focused) == counts


def test_user_close_clears_explicit_activation_before_next_passive_probe():
    adapter = _PageAdapter()
    adapter.business_url = adapter.login_url
    controller, webview, _adapter = _controller(adapter=adapter, delayed=[])

    controller.prepare_session(show_login_if_required=True)
    first = webview.window
    first.events.closed.fire()

    controller.prepare_window_before_start(show_login_if_required=False)
    second = webview.window
    second.events.loaded.fire()

    assert second is not first
    assert second.shown == 0
    assert controller.get_status()["session_state"] == "login_required"


def test_close_recreate_cycles_never_accumulate_windows_or_handlers():
    controller, webview, _adapter = _controller()

    for _index in range(50):
        assert controller.prepare_session(show_login_if_required=True)["ok"] is True
        window = webview.window
        assert len(window.events.closing.handlers) == 1
        assert len(window.events.closed.handlers) == 1
        assert window.events.closing.fire() == [True]
        window.events.closed.fire()
        assert controller.get_status()["session_state"] == "idle"

    assert len(webview.calls) == 50


def test_stale_closed_callback_cannot_clear_recreated_window():
    controller, webview, _adapter = _controller()
    controller.prepare_session()
    first = webview.window
    first.events.closing.fire()
    first.events.closed.fire()
    controller.prepare_session()
    second = webview.window

    first.events.closed.fire()

    assert controller.get_status()["session_state"] == "probing"
    assert webview.window is second
    assert len(webview.calls) == 2


def test_disable_shutdown_and_renderer_failure_invalidate_all_future_callbacks():
    delayed = []
    controller, webview, _adapter = _controller(delayed=delayed)
    controller.prepare_window_before_start(show_login_if_required=False)
    first = webview.window
    callbacks = [callback for _delay, callback in delayed]
    controller.disable()
    for callback in callbacks:
        callback()
    assert first.destroyed == 1
    assert controller.get_status()["session_state"] == "idle"

    controller.prepare_session()
    second = webview.window
    controller.mark_renderer_unavailable()
    assert second.destroyed == 1
    assert controller.get_status()["error_code"] == "renderer_unavailable"
    controller.shutdown()
    assert controller.prepare_session()["error"] == "window_unavailable"


def test_diagnostics_are_stage_specific_and_never_include_query_or_url(caplog):
    controller, webview, _adapter = _controller()
    with caplog.at_level("INFO"):
        controller.prepare_window_before_start(show_login_if_required=False)
        webview.window.events.before_load.fire()
        webview.window.events.loaded.fire()
        controller.search_cases("SECRET CASE")

    joined = "\n".join(record.getMessage() for record in caplog.records)
    for event in (
        "fd_work_page_phase_changed",
        "fd_work_adapter_installed",
        "fd_work_interactive_lease_begin",
        "fd_work_interactive_lease_ready",
        "fd_work_case_lookup_stage",
        "fd_work_case_lookup_completed",
    ):
        assert event in joined
    assert "session_state=" in joined
    assert "page_phase=" in joined
    assert "navigation_generation=" in joined
    assert "document_visibility=visible" in joined
    assert "SECRET CASE" not in joined
    assert "https://" not in joined
    assert "password" not in joined.lower()


def test_navigation_block_is_fail_closed_without_reload_loop():
    controller, webview, _adapter = _controller()
    controller.prepare_session(show_login_if_required=True)
    webview.window.url = "https://example.com/Login"

    webview.window.events.loaded.fire()

    assert controller.get_status()["session_state"] == "error"
    assert controller.get_status()["error_code"] == "navigation_blocked"
    assert webview.window.loaded_urls == []
