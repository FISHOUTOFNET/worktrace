from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from worktrace.collector.single_instance import ApplicationInstanceCoordinator
from worktrace.desktop.update_shutdown import ApplicationUpdateShutdownCoordinator
from worktrace.desktop.windows_tray import WindowsTrayHost


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _ActivationKernel:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.wait_calls = 0

    def create_activation_event(self, _name: str):
        return self.event

    def signal_prepared_activation(self, event) -> bool:
        event.set()
        return True

    def signal_activation_event(self, _name: str) -> bool:
        self.event.set()
        return True

    def wait_for_activation(self, event, timeout_seconds: float) -> bool:
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise OSError("synthetic wait failure")
        signaled = event.wait(timeout_seconds)
        if signaled:
            event.clear()
        return signaled

    def wake_activation_waiter(self, event) -> None:
        event.set()

    def close_activation_event(self, _event) -> None:
        return None


class _UpdateKernel:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.wait_calls = 0
        self.running = False

    def create_event(self, _name: str):
        self.running = True
        return self.event

    def event_exists(self, _name: str) -> bool:
        return self.running

    def signal_event(self, _name: str) -> bool:
        self.event.set()
        return True

    def wait_for_signal(self, event, timeout_seconds: float) -> bool:
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise OSError("synthetic wait failure")
        signaled = event.wait(timeout_seconds)
        if signaled:
            event.clear()
        return signaled

    def wake_waiter(self, event) -> None:
        event.set()

    def close_event(self, _event) -> None:
        self.running = False


def test_activation_listener_survives_one_wait_failure() -> None:
    kernel = _ActivationKernel()
    coordinator = ApplicationInstanceCoordinator(kernel=kernel)
    activated = threading.Event()

    coordinator.prepare_activation_event()
    coordinator.start_activation_listener()
    coordinator.bind_activation_handler(activated.set)
    try:
        assert coordinator.signal_existing_instance() is True
        assert activated.wait(1.0)
        assert kernel.wait_calls >= 2
        assert coordinator._thread is not None
        assert coordinator._thread.is_alive()
    finally:
        coordinator.stop_activation_listener()


def test_update_listener_survives_one_wait_failure() -> None:
    kernel = _UpdateKernel()
    coordinator = ApplicationUpdateShutdownCoordinator(kernel=kernel)
    shutdown = threading.Event()

    coordinator.prepare()
    coordinator.start_listener()
    coordinator.bind_shutdown_handler(shutdown.set)
    try:
        assert coordinator.signal_running_instance() is True
        assert shutdown.wait(1.0)
        assert kernel.wait_calls >= 2
        assert coordinator._thread is not None
        assert coordinator._thread.is_alive()
    finally:
        coordinator.close()


def test_tray_message_loop_restarts_after_ready_runtime_failure(
    monkeypatch,
) -> None:
    pump_calls = 0
    tray: WindowsTrayHost | None = None

    class _WndClass:
        hInstance = None
        lpszClassName = ""
        lpfnWndProc = None

    def pump_messages() -> None:
        nonlocal pump_calls
        pump_calls += 1
        if pump_calls == 1:
            raise OSError("synthetic tray pump failure")
        assert tray is not None
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
        CreateWindow=lambda *_args: 123,
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
    tray._RESTART_INITIAL_SECONDS = 0.0
    tray._RESTART_MAX_SECONDS = 0.0

    tray._run()

    assert tray._ready.is_set()
    assert not tray._failed.is_set()
    assert pump_calls == 2
