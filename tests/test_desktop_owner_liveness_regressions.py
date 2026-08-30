from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from worktrace.collector import single_instance
from worktrace.collector.single_instance import (
    ApplicationInstanceCoordinator,
    SingleInstanceError,
    WindowsActivationKernel,
)
from worktrace.desktop import update_shutdown
from worktrace.desktop.shell import DesktopShellController, ShellState
from worktrace.desktop.update_shutdown import (
    ApplicationUpdateShutdownCoordinator,
    UpdateShutdownError,
    WindowsUpdateShutdownKernel,
)
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


def test_activation_kernel_distinguishes_timeout_failed_and_unknown(monkeypatch) -> None:
    result = {"value": WindowsActivationKernel.WAIT_TIMEOUT}
    fake_kernel32 = SimpleNamespace(
        WaitForSingleObject=lambda _event, _timeout: result["value"]
    )
    monkeypatch.setattr(
        WindowsActivationKernel,
        "_kernel32",
        staticmethod(lambda: fake_kernel32),
    )
    monkeypatch.setattr(single_instance.ctypes, "get_last_error", lambda: 6, raising=False)
    kernel = WindowsActivationKernel()

    assert kernel.wait_for_activation(object(), 0.01) is False

    result["value"] = WindowsActivationKernel.WAIT_FAILED
    with pytest.raises(SingleInstanceError, match="activation_wait_failed:6"):
        kernel.wait_for_activation(object(), 0.01)

    result["value"] = 12345
    with pytest.raises(SingleInstanceError, match="activation_wait_unexpected:12345"):
        kernel.wait_for_activation(object(), 0.01)


def test_update_kernel_distinguishes_timeout_failed_and_unknown(monkeypatch) -> None:
    result = {"value": WindowsUpdateShutdownKernel.WAIT_TIMEOUT}
    fake_kernel32 = SimpleNamespace(
        WaitForSingleObject=lambda _event, _timeout: result["value"]
    )
    monkeypatch.setattr(
        WindowsUpdateShutdownKernel,
        "_kernel32",
        staticmethod(lambda: fake_kernel32),
    )
    monkeypatch.setattr(update_shutdown.ctypes, "get_last_error", lambda: 7, raising=False)
    kernel = WindowsUpdateShutdownKernel()

    assert kernel.wait_for_signal(object(), 0.01) is False

    result["value"] = WindowsUpdateShutdownKernel.WAIT_FAILED
    with pytest.raises(UpdateShutdownError, match="update_shutdown_wait_failed:7"):
        kernel.wait_for_signal(object(), 0.01)

    result["value"] = 54321
    with pytest.raises(UpdateShutdownError, match="update_shutdown_wait_unexpected:54321"):
        kernel.wait_for_signal(object(), 0.01)


def test_tray_restore_capability_requires_live_registered_icon() -> None:
    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: None,
        on_exit=lambda: None,
    )
    stop = threading.Event()
    thread = threading.Thread(target=stop.wait, args=(1.0,), daemon=True)
    thread.start()
    try:
        tray._thread = thread
        tray._ready.set()
        tray._hwnd = 123
        tray._icon_handle = object()
        tray._icon_registered = True
        assert tray.can_restore_window() is True

        tray._icon_registered = False
        assert tray.can_restore_window() is False
        assert tray.is_running() is False
    finally:
        stop.set()
        thread.join(timeout=1.0)


def test_shell_refuses_hide_when_tray_restore_entry_is_unavailable() -> None:
    class Tray:
        def __init__(self) -> None:
            self.restore = True

        def start(self):
            return True

        def stop(self):
            return None

        def can_restore_window(self):
            return self.restore

        def show_background_notice(self):
            return None

        def set_collection_active(self, _active):
            return None

    class Window:
        def __init__(self) -> None:
            self.hidden = 0

        def hide(self):
            self.hidden += 1

        def evaluate_js(self, _source):
            return None

    tray = Tray()
    window = Window()
    scheduled = []
    shell = DesktopShellController(
        window=window,
        tray=tray,
        deferred_window_action_executor=scheduled.append,
    )
    assert shell.start() is True
    tray.restore = False

    assert shell.hide_window() is False
    assert shell.state is ShellState.VISIBLE
    assert window.hidden == 0
    assert scheduled == []


def test_shell_rechecks_tray_before_deferred_hide() -> None:
    class Tray:
        def __init__(self) -> None:
            self.restore = True

        def start(self):
            return True

        def stop(self):
            return None

        def can_restore_window(self):
            return self.restore

        def show_background_notice(self):
            return None

        def set_collection_active(self, _active):
            return None

    class Window:
        def __init__(self) -> None:
            self.hidden = 0

        def hide(self):
            self.hidden += 1

        def evaluate_js(self, _source):
            return None

    tray = Tray()
    window = Window()
    scheduled = []
    shell = DesktopShellController(
        window=window,
        tray=tray,
        deferred_window_action_executor=scheduled.append,
    )
    assert shell.start() is True
    assert shell.hide_window() is True
    assert len(scheduled) == 1

    tray.restore = False
    scheduled.pop()()

    assert shell.state is ShellState.VISIBLE
    assert window.hidden == 0


def test_shell_recovers_if_tray_disappears_immediately_after_native_hide() -> None:
    class Tray:
        def __init__(self) -> None:
            self.checks = 0

        def start(self):
            return True

        def stop(self):
            return None

        def can_restore_window(self):
            self.checks += 1
            return self.checks < 3

        def show_background_notice(self):
            return None

        def set_collection_active(self, _active):
            return None

    class Window:
        def __init__(self) -> None:
            self.hidden = 0
            self.shown = 0
            self.restored = 0

        def hide(self):
            self.hidden += 1

        def show(self):
            self.shown += 1

        def restore(self):
            self.restored += 1

        def evaluate_js(self, _source):
            return None

    tray = Tray()
    window = Window()
    scheduled = []
    shell = DesktopShellController(
        window=window,
        tray=tray,
        deferred_window_action_executor=scheduled.append,
    )
    assert shell.start() is True
    assert shell.hide_window() is True
    scheduled.pop()()

    assert window.hidden == 1
    assert window.shown == 1
    assert window.restored == 1
    assert shell.state is ShellState.VISIBLE


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
    assert tray.can_restore_window() is False
