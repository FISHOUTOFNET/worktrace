from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from worktrace.desktop.windows_tray import WindowsTrayHost


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


def test_collection_state_updates_desired_handle_while_registration_is_down() -> None:
    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: None,
        on_exit=lambda: None,
    )
    inactive = object()
    active = object()
    tray._hwnd = 123
    tray._inactive_icon_handle = inactive
    tray._active_icon_handle = active
    tray._icon_handle = inactive
    tray._icon_registered = False
    tray._collection_active = False

    tray.set_collection_active(True)

    assert tray._collection_active is True
    assert tray._icon_handle is active
    assert tray._icon_registered is False


def test_taskbar_reregistration_success_keeps_current_generation(monkeypatch) -> None:
    add_calls: list[tuple[int, object]] = []
    destroyed: list[int] = []
    fake_gui = SimpleNamespace(
        NIM_ADD=0,
        NIM_DELETE=1,
        NIM_MODIFY=2,
        NIF_ICON=1,
        NIF_MESSAGE=2,
        NIF_TIP=4,
        Shell_NotifyIcon=lambda op, data: add_calls.append((op, data[4])),
        DestroyWindow=destroyed.append,
    )
    monkeypatch.setitem(sys.modules, "win32gui", fake_gui)

    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: None,
        on_exit=lambda: None,
    )
    active = object()
    tray._hwnd = 123
    tray._active_icon_handle = active
    tray._inactive_icon_handle = object()
    tray._icon_handle = active
    tray._collection_active = True
    tray._icon_registered = True

    tray._on_taskbar_created(123, 0, 0, 0)

    assert tray._icon_registered is True
    assert add_calls == [(fake_gui.NIM_ADD, active)]
    assert destroyed == []


def test_taskbar_reregistration_failure_restarts_generation_and_replays_latest_state(
    monkeypatch,
) -> None:
    tray: WindowsTrayHost | None = None
    create_calls: list[int] = []
    destroyed: list[int] = []
    add_icons: list[object] = []
    add_count = 0
    pump_count = 0

    class _WndClass:
        hInstance = None
        lpszClassName = ""
        lpfnWndProc = None

    def create_window(*_args) -> int:
        hwnd = 100 + len(create_calls) + 1
        create_calls.append(hwnd)
        return hwnd

    def shell_notify_icon(op, data) -> None:
        nonlocal add_count
        if op != fake_gui.NIM_ADD:
            return
        add_count += 1
        add_icons.append(data[4])
        if add_count == 2:
            assert tray is not None
            # The projection changes while Explorer registration is unavailable.
            # Recovery must carry this desired state into the next generation.
            tray.set_collection_active(False)
            raise OSError("synthetic TaskbarCreated NIM_ADD failure")

    def pump_messages() -> None:
        nonlocal pump_count
        pump_count += 1
        assert tray is not None
        if pump_count == 1:
            hwnd = tray._hwnd
            assert hwnd is not None
            tray._on_taskbar_created(hwnd, tray._taskbar_created, 0, 0)
            assert tray._icon_registered is False
            return
        tray._stop_requested.set()

    fake_gui = SimpleNamespace(
        WNDCLASS=_WndClass,
        NIM_ADD=0,
        NIM_DELETE=1,
        NIM_MODIFY=2,
        NIF_ICON=1,
        NIF_MESSAGE=2,
        NIF_TIP=4,
        RegisterWindowMessage=lambda _name: 99,
        RegisterClass=lambda _wc: None,
        CreateWindow=create_window,
        Shell_NotifyIcon=shell_notify_icon,
        DestroyIcon=lambda _handle: None,
        DestroyWindow=destroyed.append,
        PostQuitMessage=lambda _code: None,
        PumpMessages=pump_messages,
    )
    fake_api = SimpleNamespace(GetModuleHandle=lambda _value: 1)
    fake_con = SimpleNamespace(
        WM_COMMAND=1,
        WM_DESTROY=2,
        WM_QUERYENDSESSION=3,
        WM_ENDSESSION=4,
        WM_LBUTTONDBLCLK=5,
        WM_RBUTTONUP=6,
    )
    monkeypatch.setitem(sys.modules, "win32gui", fake_gui)
    monkeypatch.setitem(sys.modules, "win32api", fake_api)
    monkeypatch.setitem(sys.modules, "win32con", fake_con)

    def load_variant(_path, *, active: bool):
        generation = len(create_calls)
        return ("active" if active else "inactive", generation)

    monkeypatch.setattr(
        "worktrace.desktop.windows_tray.load_icon_variant",
        load_variant,
    )

    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: None,
        on_exit=lambda: None,
    )
    tray._RESTART_INITIAL_SECONDS = 0.0
    tray._RESTART_MAX_SECONDS = 0.0
    tray._thread = threading.current_thread()
    tray.set_collection_active(True)

    tray._run()

    assert create_calls == [101, 102]
    assert destroyed == [101]
    assert add_count == 3
    assert add_icons[0] == ("active", 1)
    assert add_icons[1] == ("active", 1)
    assert add_icons[2] == ("inactive", 2)
    assert pump_count == 2
    assert tray._collection_active is False
    assert tray._thread is None
    assert tray.can_restore_window() is False


def test_stop_requested_during_restart_backoff_prevents_new_generation(
    monkeypatch,
) -> None:
    tray: WindowsTrayHost | None = None
    create_calls = 0

    class _WndClass:
        hInstance = None
        lpszClassName = ""
        lpfnWndProc = None

    def create_window(*_args) -> int:
        nonlocal create_calls
        create_calls += 1
        return 123

    def pump_messages() -> None:
        raise OSError("synthetic message-loop failure")

    fake_gui = SimpleNamespace(
        WNDCLASS=_WndClass,
        NIM_ADD=0,
        NIM_DELETE=1,
        NIM_MODIFY=2,
        NIF_ICON=1,
        NIF_MESSAGE=2,
        NIF_TIP=4,
        RegisterWindowMessage=lambda _name: 99,
        RegisterClass=lambda _wc: None,
        CreateWindow=create_window,
        Shell_NotifyIcon=lambda *_args: None,
        DestroyIcon=lambda _handle: None,
        DestroyWindow=lambda _hwnd: None,
        PumpMessages=pump_messages,
    )
    fake_api = SimpleNamespace(GetModuleHandle=lambda _value: 1)
    fake_con = SimpleNamespace(
        WM_COMMAND=1,
        WM_DESTROY=2,
        WM_QUERYENDSESSION=3,
        WM_ENDSESSION=4,
        WM_LBUTTONDBLCLK=5,
        WM_RBUTTONUP=6,
    )
    monkeypatch.setitem(sys.modules, "win32gui", fake_gui)
    monkeypatch.setitem(sys.modules, "win32api", fake_api)
    monkeypatch.setitem(sys.modules, "win32con", fake_con)
    monkeypatch.setattr(
        "worktrace.desktop.windows_tray.load_icon_variant",
        lambda *_args, **_kwargs: object(),
    )

    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: None,
        on_exit=lambda: None,
    )
    tray._RESTART_INITIAL_SECONDS = 0.5
    tray._RESTART_MAX_SECONDS = 0.5
    stopper = threading.Timer(0.01, tray._stop_requested.set)
    stopper.start()
    try:
        tray._run()
    finally:
        stopper.cancel()
        stopper.join(timeout=1.0)

    assert create_calls == 1
