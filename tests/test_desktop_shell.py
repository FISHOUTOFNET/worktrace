from __future__ import annotations

import sys
from collections.abc import Callable
from types import SimpleNamespace

from worktrace.desktop import shell as shell_module
from worktrace.desktop.shell import DesktopShellController, ShellState


class FakeWindow:
    def __init__(
        self,
        *,
        fail_hide: bool = False,
        fail_destroy: bool = False,
        focus: bool = True,
    ) -> None:
        self.calls: list[str] = []
        self.fail_hide = fail_hide
        self.fail_destroy = fail_destroy
        self.focus = focus
        self.native = None

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
        if self.fail_destroy:
            raise RuntimeError("destroy failed")

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
    fail_destroy: bool = False,
) -> tuple[DesktopShellController, FakeWindow, FakeTray, ManualWindowActions]:
    window = FakeWindow(
        fail_hide=fail_hide,
        fail_destroy=fail_destroy,
        focus=not initial_hidden,
    )
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


def test_exit_request_cancels_pending_hide_and_terminalizes_shell() -> None:
    shell, window, tray, actions = _shell()
    shell.start()
    shell.handle_window_closing()

    assert shell.exit_application() is True
    actions.run_all()

    assert "hide" not in window.calls
    assert window.calls.count("destroy") == 1
    assert shell.state is ShellState.EXITING
    assert tray.stop_calls == 1

    shell.stop()
    assert tray.stop_calls == 1


def test_exit_stops_tray_only_after_main_window_destroy_returns() -> None:
    shell, window, tray, _actions = _shell()
    operations: list[str] = []

    def destroy() -> None:
        operations.append("destroy")

    def stop() -> None:
        operations.append("tray_stop")
        tray.stop_calls += 1

    window.destroy = destroy
    tray.stop = stop
    shell.start()

    assert shell.exit_application() is True

    assert operations == ["destroy", "tray_stop"]
    assert tray.stop_calls == 1


def test_failed_exit_destroy_keeps_tray_and_allows_retry() -> None:
    shell, window, tray, actions = _shell(fail_destroy=True)
    shell.start()

    assert shell.exit_application() is False
    actions.run_all()

    assert window.calls.count("destroy") == 1
    assert tray.stop_calls == 0
    assert shell.state is ShellState.EXITING

    window.fail_destroy = False
    assert shell.exit_application() is True
    actions.run_all()

    assert window.calls.count("destroy") == 2
    assert tray.stop_calls == 1

    shell.stop()
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

    assert window.focus is True
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
    assert window.focus is False
    assert window.calls == []
    assert actions.pending == []

    shell.handle_window_loaded()
    assert window.calls == []
    actions.run_all()

    assert window.focus is True
    assert window.calls[:2] == ["show", "restore"]
    assert "setShellVisibility(true)" in window.calls[-1]


def test_background_show_clears_noactivate_style_before_native_show(monkeypatch) -> None:
    operations: list[str] = []
    styles = {4242: shell_module._WS_EX_NOACTIVATE | 0x20}

    class _Handle:
        @staticmethod
        def ToInt32() -> int:
            return 4242

    fake_win32gui = SimpleNamespace(
        GetWindowLong=lambda hwnd, index: styles[hwnd],
        SetWindowLong=lambda hwnd, index, value: (
            operations.append("clear_noactivate"),
            styles.__setitem__(hwnd, value),
        )[-1],
        SetWindowPos=lambda *_args: operations.append("refresh_style"),
        ShowWindow=lambda *_args: operations.append("restore_native"),
        SetForegroundWindow=lambda *_args: operations.append("foreground"),
        FindWindow=lambda *_args: 0,
    )

    monkeypatch.setattr(shell_module.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)

    shell, window, _tray, actions = _shell(initial_hidden=True)
    window.native = SimpleNamespace(Handle=_Handle())
    original_show = window.show

    def show() -> None:
        operations.append("show")
        original_show()

    window.show = show
    shell.start()
    shell.show_window()
    shell.handle_window_loaded()
    actions.run_all()

    assert window.focus is True
    assert styles[4242] & shell_module._WS_EX_NOACTIVATE == 0
    assert operations.index("clear_noactivate") < operations.index("show")
    assert "refresh_style" in operations
    assert operations[-2:] == ["restore_native", "foreground"]


def test_tray_exit_only_requests_one_real_window_exit() -> None:
    shell, window, tray, actions = _shell()
    shell.start()

    assert shell.exit_application() is True
    assert shell.handle_window_closing() is True
    assert shell.exit_application() is False
    actions.run_all()

    assert window.calls.count("destroy") == 1
    assert tray.stop_calls == 1

    shell.stop()
    assert tray.stop_calls == 1
