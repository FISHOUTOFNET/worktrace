from __future__ import annotations

from collections.abc import Callable

from worktrace.desktop.shell import DesktopShellController, ShellState


class FakeWindow:
    def __init__(self, *, fail_hide: bool = False) -> None:
        self.calls: list[str] = []
        self.fail_hide = fail_hide

    def hide(self) -> None:
        self.calls.append("hide")
        if self.fail_hide:
            raise RuntimeError("hide failed")

    def show(self) -> None:
        self.calls.append("show")

    def restore(self) -> None:
        self.calls.append("restore")

    def destroy(self) -> None:
        self.calls.append("destroy")

    def evaluate_js(self, source: str) -> None:
        self.calls.append(source)


class FakeTray:
    def __init__(self, starts: bool = True) -> None:
        self.starts = starts
        self.stop_calls = 0
        self.notifications = 0

    def start(self) -> bool:
        return self.starts

    def stop(self) -> None:
        self.stop_calls += 1

    def show_background_notice(self) -> None:
        self.notifications += 1


class ManualWindowActions:
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def submit(self, action: Callable[[], None]) -> None:
        self.pending.append(action)

    def run_next(self) -> None:
        self.pending.pop(0)()

    def run_all(self) -> None:
        while self.pending:
            self.run_next()


def _shell(
    *,
    initial_hidden: bool = False,
    tray_starts: bool = True,
    fail_hide: bool = False,
) -> tuple[DesktopShellController, FakeWindow, FakeTray, ManualWindowActions]:
    window = FakeWindow(fail_hide=fail_hide)
    tray = FakeTray(starts=tray_starts)
    actions = ManualWindowActions()
    shell = DesktopShellController(
        window=window,
        tray=tray,
        initial_hidden=initial_hidden,
        deferred_window_action_executor=actions.submit,
    )
    return shell, window, tray, actions


def test_close_callback_only_schedules_hide_before_return() -> None:
    shell, window, tray, actions = _shell()
    assert shell.start() is True

    assert shell.handle_window_closing() is False

    assert shell.state is ShellState.HIDDEN
    assert window.calls == []
    assert tray.notifications == 0
    assert len(actions.pending) == 1


def test_deferred_close_hides_once_then_notifies_frontend_and_tray() -> None:
    shell, window, tray, actions = _shell()
    shell.start()

    assert shell.handle_window_closing() is False
    assert shell.handle_window_closing() is False
    assert len(actions.pending) == 1

    actions.run_all()

    assert window.calls[0] == "hide"
    assert "setShellVisibility(false)" in window.calls[1]
    assert window.calls.count("hide") == 1
    assert tray.notifications == 1


def test_hide_failure_restores_visible_state_without_hidden_notification() -> None:
    shell, window, tray, actions = _shell(fail_hide=True)
    shell.start()

    assert shell.handle_window_closing() is False
    actions.run_all()

    assert shell.state is ShellState.VISIBLE
    assert window.calls == ["hide"]
    assert tray.notifications == 0


def test_show_request_cancels_pending_hide() -> None:
    shell, window, tray, actions = _shell()
    shell.start()
    shell.handle_window_loaded()
    actions.run_all()
    window.calls.clear()

    shell.handle_window_closing()
    assert shell.show_window() is True
    actions.run_all()

    assert "hide" not in window.calls
    assert shell.state is ShellState.VISIBLE
    assert tray.notifications == 0


def test_exit_request_cancels_pending_hide() -> None:
    shell, window, tray, actions = _shell()
    shell.start()
    shell.handle_window_closing()

    assert shell.exit_application() is True
    actions.run_all()

    assert "hide" not in window.calls
    assert window.calls.count("destroy") == 1
    assert shell.state is ShellState.EXITING
    assert tray.stop_calls == 1


def test_initial_hidden_tray_failure_uses_no_window_api_before_loaded() -> None:
    shell, window, _tray, actions = _shell(
        initial_hidden=True,
        tray_starts=False,
    )

    assert shell.start() is False

    assert shell.state is ShellState.VISIBLE
    assert window.calls == []
    assert actions.pending == []


def test_initial_hidden_tray_failure_shows_after_loaded() -> None:
    shell, window, _tray, actions = _shell(
        initial_hidden=True,
        tray_starts=False,
    )
    shell.start()

    shell.handle_window_loaded()
    assert window.calls == []
    actions.run_all()

    assert window.calls[:2] == ["show", "restore"]
    assert "setShellVisibility(true)" in window.calls[-1]


def test_tray_failure_preserves_normal_window_close() -> None:
    shell, window, _tray, _actions = _shell(tray_starts=False)

    assert shell.start() is False
    assert shell.handle_window_closing() is True
    assert shell.state is ShellState.EXITING
    assert window.calls == []


def test_activation_before_loaded_records_show_intent_only() -> None:
    shell, window, _tray, actions = _shell(initial_hidden=True)
    shell.start()

    assert shell.show_window() is True
    assert shell.state is ShellState.VISIBLE
    assert window.calls == []
    assert actions.pending == []

    shell.handle_window_loaded()
    assert window.calls == []
    actions.run_all()

    assert window.calls[:2] == ["show", "restore"]
    assert "setShellVisibility(true)" in window.calls[-1]


def test_tray_exit_only_requests_one_real_window_exit() -> None:
    shell, window, tray, actions = _shell()
    shell.start()

    shell.exit_application()
    assert shell.handle_window_closing() is True
    shell.exit_application()
    actions.run_all()

    assert window.calls.count("destroy") == 1
    assert tray.stop_calls == 1
