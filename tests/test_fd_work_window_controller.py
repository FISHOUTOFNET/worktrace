from __future__ import annotations

from dataclasses import dataclass
import threading

import pytest
from webview.event import Event as PyWebViewEvent

from worktrace.integrations.fd_work import window_controller as controller_module
from worktrace.integrations.fd_work.window_controller import FDWorkWindowController
from worktrace.integrations.fd_work.window_executor import FDWorkWindowExecutor


pytestmark = [
    pytest.mark.integration,
    pytest.mark.collector_runtime,
    pytest.mark.contract,
    pytest.mark.serial,
]


@pytest.fixture(autouse=True)
def _stub_native_window_activation(monkeypatch):
    """Keep controller tests platform-neutral; native activation has its own tests."""

    monkeypatch.setattr(
        controller_module,
        "make_window_activatable",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        controller_module,
        "request_window_foreground",
        lambda *_args, **_kwargs: True,
    )


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
        self.actions = []

    def get_current_url(self):
        return self.url

    def show(self):
        self.shown += 1
        self.actions.append("show")

    def hide(self):
        self.hidden += 1
        self.actions.append("hide")

    def restore(self):
        self.restored += 1
        self.actions.append("restore")

    def focus(self):
        self.focused += 1
        self.actions.append("focus")

    def destroy(self):
        self.destroyed += 1
        self.actions.append("destroy")


class _WebView:
    def __init__(self, business_url: str) -> None:
        self.business_url = business_url
        self.calls = []
        self.window = None

    def create_window(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.window = _Window(self.business_url)
        return self.window


@dataclass
class _PageAdapter:
    business_url: str = "https://work.fangdalaw.com/Works/WorkHourList?picker=day"
    login_url: str = "https://work.fangdalaw.com/Login"

    def __post_init__(self):
        self.install_calls = []
        self.install_result = {"ok": True, "version": 5}
        self.cancel_pending_calls = []

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
        else:
            callback({"phase": "unknown"})

    def install_adapter(self, window):
        self.install_calls.append(window)
        return dict(self.install_result)

    def cancel_pending_actions(self, error_kind):
        self.cancel_pending_calls.append(error_kind)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _controller(
    *,
    adapter=None,
    delayed=None,
    renderer_initialized=True,
    helper_bridge=None,
    close_results=None,
    main_focus=None,
    clock=None,
    **kwargs,
):
    adapter = adapter or _PageAdapter()
    webview = _WebView(adapter.business_url)
    controller = FDWorkWindowController(
        webview,
        page_adapter=adapter,
        helper_bridge=helper_bridge,
        schedule=lambda callback: callback(),
        schedule_after=(
            (lambda delay, callback: delayed.append((delay, callback)))
            if delayed is not None
            else lambda _delay, _callback: None
        ),
        clock=clock or __import__("time").monotonic,
        **kwargs,
    )
    if close_results is not None:
        controller.bind_close_callback(close_results.append)
    if main_focus is not None:
        controller.bind_main_focus_callback(main_focus)
    if renderer_initialized:
        controller.on_renderer_initialized("edgechromium")
    return controller, webview, adapter


def _run_next(delayed, clock=None):
    delay, callback = delayed.pop(0)
    if clock is not None:
        clock.advance(delay)
    callback()
    return delay


def test_passive_prestart_creates_one_hidden_window_with_narrow_helper_bridge():
    helper_bridge = object()
    controller, webview, _adapter = _controller(
        renderer_initialized=False,
        helper_bridge=helper_bridge,
    )

    first = controller.prepare_window_before_start(False)
    second = controller.prepare_window_before_start(False)

    assert first["ok"] is True and second["ok"] is True
    assert len(webview.calls) == 1
    _args, kwargs = webview.calls[0]
    assert kwargs["hidden"] is True
    assert kwargs["focus"] is False
    assert kwargs["js_api"] is helper_bridge
    assert webview.window.shown == 0
    assert len(webview.window.events.closing.handlers) == 1


def test_navigation_and_close_cancel_pending_adapter_message_results():
    controller, webview, adapter = _controller(renderer_initialized=False)
    controller.prepare_window_before_start(False)
    window = webview.window

    window.events.before_load.fire()
    window.events.closing.fire()

    assert adapter.cancel_pending_calls == ["navigation_changed", "window_closed"]


def test_explicit_auth_show_restore_focus_runs_once_through_executor():
    controller, webview, _adapter = _controller()

    result = controller.prepare_session(True)

    assert result["ok"] is True
    assert (webview.window.shown, webview.window.restored, webview.window.focused) == (1, 1, 1)


@pytest.mark.parametrize(
    ("path", "phase"),
    [("Login", "login_credentials"), ("LoginToken", "login_confirmation")],
)
def test_login_phases_do_not_repeat_foreground_mutation(path, phase):
    controller, webview, _adapter = _controller(delayed=[])
    controller.prepare_session(True)
    webview.window.url = f"https://work.fangdalaw.com/{path}"

    webview.window.events.loaded.fire()

    status = controller.get_status()
    assert status["session_state"] == "login_required"
    assert status["page_phase"] == phase
    assert (webview.window.shown, webview.window.restored, webview.window.focused) == (1, 1, 1)


def test_passive_probe_never_mutates_window_visibility_or_focus():
    delayed = []
    controller, webview, _adapter = _controller(renderer_initialized=False, delayed=delayed)
    controller.prepare_window_before_start(False)
    controller.on_renderer_initialized("edgechromium")
    _run_next(delayed)

    assert (webview.window.shown, webview.window.restored, webview.window.focused) == (0, 0, 0)
    assert controller.get_status()["session_state"] == "ready"
    assert webview.window.hidden == 0


def test_passive_unknown_probe_uses_one_bounded_deadline():
    delayed = []
    clock = _Clock()
    controller, webview, _adapter = _controller(
        renderer_initialized=False,
        delayed=delayed,
        clock=clock,
        passive_probe_timeout_seconds=2.0,
        probe_interval_seconds=0.5,
    )
    controller.prepare_window_before_start(False)
    webview.window.url = "https://work.fangdalaw.com/loading"
    controller.on_renderer_initialized("edgechromium")

    while delayed:
        _run_next(delayed, clock)

    assert clock.now <= 102.0
    assert controller.get_status()["session_state"] == "idle"
    assert controller.get_status()["error_code"] == "session_probe_inconclusive"
    assert webview.window.shown == 0


def test_probe_timeout_logs_only_safe_dom_contract_booleans(caplog):
    delayed = []
    clock = _Clock()
    adapter = _PageAdapter()

    def probe_page_phase(_window, callback):
        callback({
            "phase": "unknown",
            "input_exists": True,
            "form_exists": True,
            "wrapper_exists": False,
            "role_matches": False,
        })

    adapter.probe_page_phase = probe_page_phase
    controller, _webview, _adapter = _controller(
        adapter=adapter,
        delayed=delayed,
        renderer_initialized=False,
        passive_probe_timeout_seconds=0.2,
        probe_interval_seconds=0.1,
        clock=clock,
    )
    caplog.set_level("INFO")
    controller.prepare_window_before_start(False)
    controller.on_renderer_initialized("edgechromium")

    while delayed:
        _run_next(delayed, clock)

    messages = [record.getMessage() for record in caplog.records]
    timeout = next(message for message in messages if "session_probe_inconclusive" in message)
    assert "input_exists=True" in timeout
    assert "form_exists=True" in timeout
    assert "wrapper_exists=False" in timeout
    assert "role_matches=False" in timeout


def test_controller_ready_status_does_not_claim_login_visibility_ownership():
    observed = []
    controller, webview, adapter = _controller(delayed=[])
    controller.bind_status_callback(
        lambda status: observed.append((dict(status), webview.window.hidden))
    )
    controller.prepare_session(True)
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()
    webview.window.url = adapter.business_url

    webview.window.events.loaded.fire()

    ready = [item for item in observed if item[0]["session_state"] == "ready"]
    assert ready and ready[-1][1] == 0


def test_ready_work_shell_keeps_visible_helper_for_login_to_picker_handoff():
    controller, webview, adapter = _controller(delayed=[])
    controller.prepare_session(True)
    webview.window.url = adapter.login_url
    webview.window.events.loaded.fire()
    webview.window.url = adapter.business_url

    webview.window.events.loaded.fire()
    shown_before = webview.window.shown
    context = controller.foreground("user_picker", 7, lambda: True)

    assert context["ok"] is True
    assert webview.window.actions == ["show", "restore", "focus"]
    assert webview.window.hidden == 0
    assert webview.window.shown == shown_before


def test_adapter_installs_once_per_navigation_and_v5_mismatch_fails_closed():
    controller, webview, adapter = _controller()
    controller.prepare_window_before_start(False)
    webview.window.events.loaded.fire()
    assert len(adapter.install_calls) == 1

    controller.prepare_window_before_start(False)
    assert len(adapter.install_calls) == 1
    adapter.install_result = {"ok": False, "error": "adapter_injection_failed"}
    webview.window.events.loaded.fire()
    assert controller.get_status()["session_state"] == "error"
    assert controller.get_status()["error_code"] == "adapter_injection_failed"


def test_explicit_picker_foreground_is_one_show_restore_focus_sequence():
    controller, webview, _adapter = _controller()
    controller.prepare_window_before_start(False)
    webview.window.events.loaded.fire()
    shown_before = webview.window.shown

    context = controller.foreground("user_picker", 7, lambda: True)

    assert context["ok"] is True
    assert context["navigation_generation"] == controller.get_status()["navigation_generation"]
    assert webview.window.shown == shown_before + 1
    assert webview.window.restored == 1
    assert webview.window.focused == 1


def test_picker_finish_restores_main_before_hiding_helper_in_same_dispatch():
    actions = []

    def restore_main() -> bool:
        actions.append("main")
        return True

    controller, webview, _adapter = _controller(main_focus=restore_main)
    controller.prepare_window_before_start(False)
    webview.window.events.loaded.fire()
    context = controller.foreground("user_picker", 1, lambda: True)
    generation = context["navigation_generation"]
    webview.window.hide = lambda: actions.append("hide")

    controller.hide_and_restore_main(generation, 1, lambda: True)

    assert actions == ["main", "hide"]


def test_stale_queued_foreground_mutation_cannot_touch_recreated_window():
    executor = FDWorkWindowExecutor(name="fd-work-controller-stale-test")
    command_started = threading.Event()
    command_release = threading.Event()
    blocker = threading.Thread(
        target=lambda: executor.submit(
            lambda done: (
                command_started.set(),
                command_release.wait(timeout=1),
                done(True),
            ),
            lambda: True,
            1,
        )
    )
    blocker.start()
    assert command_started.wait(timeout=1)
    controller, webview, _adapter = _controller(window_executor=executor)
    outcome = {}
    prepare = threading.Thread(
        target=lambda: outcome.setdefault("result", controller.prepare_session(True))
    )
    prepare.start()
    assert executor.wait_for_pending_count(1, timeout=1)
    first = webview.window
    assert first.events.closing.fire() == [True]
    first.events.closed.fire()
    command_release.set()
    blocker.join(timeout=1)
    prepare.join(timeout=1)

    assert (first.shown, first.restored, first.focused) == (0, 0, 0)
    assert not blocker.is_alive()
    assert not prepare.is_alive()
    controller.shutdown()


def test_close_callback_is_nonblocking_and_recreate_does_not_accumulate_handlers():
    close_results = []
    delayed = []
    controller, webview, _adapter = _controller(
        close_results=close_results,
        delayed=delayed,
        renderer_initialized=False,
    )

    for _index in range(20):
        controller.prepare_session(True)
        window = webview.window
        worker = threading.Thread(target=window.events.closing.fire)
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert len(close_results) == _index
        window.events.closed.fire()
        assert len(delayed) == 1
        _delay, callback = delayed.pop(0)
        callback()
        assert len(close_results) == _index + 1

    assert len(close_results) == 20
    assert len(webview.calls) == 20


def test_closing_allows_native_close_and_never_runs_business_callback_inline():
    delayed = []
    callback_entered = threading.Event()
    callback_release = threading.Event()
    controller, webview, _adapter = _controller(
        delayed=delayed,
        renderer_initialized=False,
    )

    def close_callback(_generation):
        callback_entered.set()
        callback_release.wait(timeout=1)

    controller.bind_close_callback(close_callback)
    controller.prepare_session(True)
    window = webview.window

    native_closing = PyWebViewEvent(window, should_lock=True)
    native_closing += window.events.closing.handlers[0]
    assert native_closing.set() is False
    assert not callback_entered.is_set()
    assert delayed == []

    window.events.closed.fire()
    assert len(delayed) == 1
    worker = threading.Thread(target=delayed.pop(0)[1])
    worker.start()
    assert callback_entered.wait(timeout=1)
    callback_release.set()
    worker.join(timeout=1)
    assert not worker.is_alive()


def test_disable_and_shutdown_destroy_via_executor_and_reject_future_open():
    controller, webview, _adapter = _controller()
    controller.prepare_window_before_start(False)
    window = webview.window
    controller.disable()
    assert window.destroyed == 1

    controller.shutdown()
    assert controller.prepare_session(True)["error"] == "window_unavailable"


def test_window_controller_has_no_search_fill_or_interactive_handshake_owner():
    controller, _webview, _adapter = _controller()
    for retired in (
        "search_cases",
        "open_entry",
        "_begin_interactive_lease",
        "_finish_search",
    ):
        assert not hasattr(controller, retired)


def test_navigation_block_is_fail_closed():
    controller, webview, _adapter = _controller()
    controller.prepare_session(True)
    webview.window.url = "https://example.com/Login"

    webview.window.events.loaded.fire()

    assert controller.get_status()["session_state"] == "error"
    assert controller.get_status()["error_code"] == "navigation_blocked"
