from __future__ import annotations

from collections.abc import Callable

from worktrace.desktop.shell import DesktopShellController, ShellState


class ManualActions:
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def submit(self, action: Callable[[], None]) -> None:
        self.pending.append(action)

    def run_all(self) -> None:
        while self.pending:
            self.pending.pop(0)()


class FakeWindow:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.native = None

    def hide(self) -> None:
        self.events.append("window:hide")

    def show(self) -> None:
        self.events.append("window:show")

    def restore(self) -> None:
        self.events.append("window:restore")

    def destroy(self) -> None:
        self.events.append("window:destroy")

    def evaluate_js(self, source: str) -> None:
        if "setShellVisibility(false)" in source:
            self.events.append("js:hidden")
        elif "setShellVisibility(true)" in source:
            self.events.append("js:visible")


class FakeTray:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def start(self) -> bool:
        return True

    def stop(self) -> None:
        return None

    def show_background_notice(self) -> None:
        self.events.append("tray:notice")

    def set_collection_active(self, _active: bool) -> None:
        return None


class FakePower:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.fail_hidden = False
        self.fail_show = False

    def enter_hidden_mode(self) -> None:
        self.events.append("power:hidden")
        if self.fail_hidden:
            raise RuntimeError("suspend failed")

    def prepare_for_show(self) -> None:
        self.events.append("power:show")
        if self.fail_show:
            raise RuntimeError("resume failed")


def _build(*, initial_hidden: bool = False):
    events: list[str] = []
    actions = ManualActions()
    power = FakePower(events)
    shell = DesktopShellController(
        window=FakeWindow(events),
        tray=FakeTray(events),
        initial_hidden=initial_hidden,
        deferred_window_action_executor=actions.submit,
        webview_power=power,
    )
    return shell, actions, power, events


def test_close_to_tray_stops_frontend_before_entering_native_hidden_mode() -> None:
    shell, actions, _power, events = _build()
    assert shell.start() is True

    assert shell.handle_window_closing() is False
    actions.run_all()

    assert shell.state is ShellState.HIDDEN
    assert events[:3] == ["window:hide", "js:hidden", "power:hidden"]
    assert events[-1] == "tray:notice"


def test_initial_hidden_window_enters_low_power_after_loaded_without_extra_hide() -> None:
    shell, actions, _power, events = _build(initial_hidden=True)
    assert shell.start() is True

    shell.handle_window_loaded()
    actions.run_all()

    assert shell.state is ShellState.HIDDEN
    assert events == ["js:hidden", "power:hidden"]


def test_show_prepares_native_renderer_before_show_and_frontend_wake() -> None:
    shell, actions, _power, events = _build()
    shell.start()
    shell.handle_window_loaded()
    actions.run_all()
    events.clear()

    shell.handle_window_closing()
    actions.run_all()
    events.clear()

    assert shell.show_window() is True
    actions.run_all()

    assert shell.state is ShellState.VISIBLE
    assert events.index("power:show") < events.index("window:show")
    assert events.index("window:show") < events.index("js:visible")


def test_power_failures_never_block_existing_shell_hide_or_show_behavior() -> None:
    shell, actions, power, events = _build()
    shell.start()
    shell.handle_window_loaded()
    actions.run_all()
    events.clear()

    power.fail_hidden = True
    shell.handle_window_closing()
    actions.run_all()
    assert shell.state is ShellState.HIDDEN
    assert "window:hide" in events
    assert "js:hidden" in events

    events.clear()
    power.fail_show = True
    assert shell.show_window() is True
    actions.run_all()
    assert shell.state is ShellState.VISIBLE
    assert "window:show" in events
    assert "js:visible" in events


def test_show_request_cancels_pending_hide_before_any_suspend_request() -> None:
    shell, actions, _power, events = _build()
    shell.start()
    shell.handle_window_loaded()
    actions.run_all()
    events.clear()

    shell.handle_window_closing()
    assert shell.show_window() is True
    actions.run_all()

    assert "window:hide" not in events
    assert "power:hidden" not in events
    assert shell.state is ShellState.VISIBLE
