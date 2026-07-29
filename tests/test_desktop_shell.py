from __future__ import annotations

from worktrace.desktop.shell import DesktopShellController, ShellState


class FakeWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def hide(self) -> None:
        self.calls.append("hide")

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


def test_close_hides_without_runtime_shutdown_when_tray_is_available() -> None:
    window = FakeWindow()
    tray = FakeTray()
    shell = DesktopShellController(window=window, tray=tray)
    assert shell.start() is True

    assert shell.handle_window_closing() is False

    assert shell.state is ShellState.HIDDEN
    assert "hide" in window.calls
    assert "destroy" not in window.calls
    assert tray.notifications == 1


def test_tray_failure_preserves_normal_window_close() -> None:
    window = FakeWindow()
    tray = FakeTray(starts=False)
    shell = DesktopShellController(window=window, tray=tray)

    assert shell.start() is False
    assert shell.handle_window_closing() is True
    assert shell.state is ShellState.EXITING
    assert "hide" not in window.calls


def test_repeated_show_hide_and_exit_are_idempotent() -> None:
    window = FakeWindow()
    tray = FakeTray()
    shell = DesktopShellController(window=window, tray=tray)
    shell.start()

    shell.hide_window()
    shell.hide_window()
    shell.show_window()
    shell.show_window()
    shell.exit_application()
    shell.exit_application()

    assert shell.state is ShellState.EXITING
    assert window.calls.count("hide") == 1
    assert window.calls.count("destroy") == 1
    assert tray.stop_calls == 1


def test_tray_exit_only_requests_one_real_window_exit() -> None:
    window = FakeWindow()
    tray = FakeTray()
    shell = DesktopShellController(window=window, tray=tray)
    shell.start()

    shell.exit_application()
    assert shell.handle_window_closing() is True
    shell.exit_application()

    assert window.calls.count("destroy") == 1
    assert tray.stop_calls == 1

