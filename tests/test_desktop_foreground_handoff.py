from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from worktrace.desktop import shell as shell_module
from worktrace.desktop.shell import DesktopShellController
from worktrace.desktop.windows_tray import WindowsTrayHost


pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


class _Actions:
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def submit(self, action: Callable[[], None]) -> None:
        self.pending.append(action)

    def run_all(self) -> None:
        while self.pending:
            self.pending.pop(0)()


class _Window:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.native = None
        self.focus = True

    def show(self) -> None:
        self.calls.append("show")

    def restore(self) -> None:
        self.calls.append("restore")

    def hide(self) -> None:
        self.calls.append("hide")

    def destroy(self) -> None:
        self.calls.append("destroy")

    def evaluate_js(self, source: str) -> None:
        self.calls.append(source)


class _Tray:
    def start(self) -> bool:
        return True

    def stop(self) -> None:
        return None

    def show_background_notice(self) -> None:
        return None

    def set_collection_active(self, _active: bool) -> None:
        return None


def _loaded_shell() -> tuple[DesktopShellController, _Window, _Actions]:
    window = _Window()
    actions = _Actions()
    shell = DesktopShellController(
        window=window,
        tray=_Tray(),
        deferred_window_action_executor=actions.submit,
    )
    shell.start()
    shell.handle_window_loaded()
    actions.run_all()
    window.calls.clear()
    return shell, window, actions


def test_loaded_visible_user_activation_stays_on_calling_thread(monkeypatch) -> None:
    shell, window, actions = _loaded_shell()
    calls: list[str] = []

    monkeypatch.setattr(shell_module.sys, "platform", "win32")
    monkeypatch.setattr(
        shell_module,
        "make_window_activatable",
        lambda *_args, **_kwargs: calls.append("activatable") or True,
    )
    monkeypatch.setattr(
        shell_module,
        "request_window_foreground",
        lambda *_args, **_kwargs: calls.append("foreground") or True,
    )

    assert shell.show_window() is True

    assert calls == ["activatable", "foreground"]
    assert actions.pending == []
    assert "show" not in window.calls
    assert "restore" not in window.calls
    assert any("setShellVisibility(true)" in call for call in window.calls)


def test_failed_inline_activation_keeps_handoff_open_and_queues_one_retry(monkeypatch) -> None:
    shell, window, actions = _loaded_shell()
    foreground_calls: list[str] = []

    monkeypatch.setattr(shell_module.sys, "platform", "win32")
    monkeypatch.setattr(
        shell_module,
        "make_window_activatable",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        shell_module,
        "request_window_foreground",
        lambda *_args, **_kwargs: foreground_calls.append("foreground") or False,
    )

    # False is intentional: FD Work uses this return value to decide whether it
    # is safe to hide the helper. The shell still schedules one bounded retry.
    assert shell.show_window() is False
    assert len(actions.pending) == 1
    assert foreground_calls == ["foreground"]

    actions.run_all()

    assert foreground_calls == ["foreground", "foreground"]
    assert window.calls[:2] == ["show", "restore"]
    assert actions.pending == []


def test_tray_open_claims_foreground_before_dispatching_open(monkeypatch) -> None:
    operations: list[object] = []
    fake_win32gui = SimpleNamespace(
        SetForegroundWindow=lambda hwnd: operations.append(("foreground", hwnd))
    )
    fake_win32con = SimpleNamespace(WM_LBUTTONDBLCLK=0x0203, WM_RBUTTONUP=0x0205)

    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)
    monkeypatch.setitem(sys.modules, "win32con", fake_win32con)

    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: operations.append("open"),
        on_exit=lambda: None,
    )

    tray._on_tray_message(777, 0, 0, fake_win32con.WM_LBUTTONDBLCLK)

    assert operations == [("foreground", 777), "open"]


def test_tray_menu_open_refreshes_foreground_handoff(monkeypatch) -> None:
    operations: list[object] = []
    fake_win32gui = SimpleNamespace(
        SetForegroundWindow=lambda hwnd: operations.append(("foreground", hwnd))
    )

    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)

    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: operations.append("open"),
        on_exit=lambda: None,
    )

    tray._on_command(888, 0, tray._CMD_OPEN, 0)

    assert operations == [("foreground", 888), "open"]
