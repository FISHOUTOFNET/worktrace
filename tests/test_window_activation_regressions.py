from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import fd_work_windows_acceptance as acceptance
from worktrace.integrations.fd_work import window_controller as controller_module
from worktrace.integrations.fd_work.window_controller import FDWorkWindowController
from worktrace.platforms import window_activation


class _Event:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def is_set(self):
        return False


class _Window:
    def __init__(self) -> None:
        self.events = SimpleNamespace(
            before_load=_Event(),
            loaded=_Event(),
            closing=_Event(),
            closed=_Event(),
        )
        self.actions: list[str] = []
        self.focus = self._focus

    def show(self) -> None:
        self.actions.append("show")

    def hide(self) -> None:
        self.actions.append("hide")

    def restore(self) -> None:
        self.actions.append("restore")

    def _focus(self) -> None:
        self.actions.append("focus")

    def destroy(self) -> None:
        self.actions.append("destroy")


class _WebView:
    def __init__(self) -> None:
        self.window = _Window()

    def create_window(self, *_args, **_kwargs):
        return self.window


class _PageAdapter:
    business_url = "https://work.fangdalaw.com/Works/WorkHourList?picker=day"

    @staticmethod
    def cancel_pending_actions(_error_kind):
        return None


def _ready_controller() -> tuple[FDWorkWindowController, _Window]:
    webview = _WebView()
    controller = FDWorkWindowController(
        webview,
        page_adapter=_PageAdapter(),
        schedule_after=lambda _delay, _callback: True,
    )
    assert controller.prepare_window_before_start(False)["ok"] is True
    with controller._lock:
        controller._session_state = "ready"
    return controller, webview.window


def test_native_activation_clears_noactivate_before_foreground(monkeypatch):
    operations: list[str] = []
    styles = {4242: window_activation.WS_EX_NOACTIVATE | 0x20}

    class _Handle:
        @staticmethod
        def ToInt32() -> int:
            return 4242

    fake_win32gui = SimpleNamespace(
        GetWindowLong=lambda hwnd, _index: styles[hwnd],
        SetWindowLong=lambda hwnd, _index, value: (
            operations.append("clear_noactivate"),
            styles.__setitem__(hwnd, value),
        )[-1],
        SetWindowPos=lambda *_args: operations.append("refresh_style"),
        ShowWindow=lambda *_args: operations.append("restore_native"),
        SetForegroundWindow=lambda *_args: operations.append("foreground"),
        FindWindow=lambda *_args: 0,
    )
    window = SimpleNamespace(
        focus=False,
        native=SimpleNamespace(Handle=_Handle()),
    )

    monkeypatch.setattr(window_activation.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)

    assert window_activation.make_window_activatable(window) is True
    assert window.focus is True
    assert styles[4242] & window_activation.WS_EX_NOACTIVATE == 0
    assert operations[:2] == ["clear_noactivate", "refresh_style"]

    assert window_activation.request_window_foreground(window) is True
    assert operations[-2:] == ["restore_native", "foreground"]


def test_visible_fd_work_helper_still_requests_native_foreground(monkeypatch):
    controller, window = _ready_controller()
    activation_calls: list[str] = []
    foreground_calls: list[bool] = []

    monkeypatch.setattr(
        controller_module,
        "make_window_activatable",
        lambda *_args, **_kwargs: activation_calls.append("enable") or True,
    )
    monkeypatch.setattr(
        controller_module,
        "request_window_foreground",
        lambda *_args, **kwargs: foreground_calls.append(bool(kwargs.get("restore"))) or True,
    )

    first = controller.foreground("user_picker", 1, lambda: True)
    assert first["ok"] is True
    assert window.actions == ["show", "restore", "focus"]
    assert activation_calls == ["enable"]
    assert foreground_calls == [True]

    window.actions.clear()
    second = controller.foreground("user_picker", 2, lambda: True)
    assert second["ok"] is True
    assert window.actions == []
    assert activation_calls == ["enable", "enable"]
    assert foreground_calls == [True, True]

    controller.shutdown()


def test_helper_visibility_commits_before_best_effort_focus(monkeypatch):
    controller, window = _ready_controller()

    def fail_focus() -> None:
        raise RuntimeError("focus failed")

    window.focus = fail_focus
    monkeypatch.setattr(
        controller_module,
        "make_window_activatable",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        controller_module,
        "request_window_foreground",
        lambda *_args, **_kwargs: False,
    )

    result = controller.foreground("user_picker", 1, lambda: True)

    assert result["ok"] is True
    assert window.actions[:2] == ["show", "restore"]
    assert controller._window_visible is True
    controller.shutdown()


def test_helper_hide_state_does_not_depend_on_main_restore_success():
    controller, window = _ready_controller()
    with controller._lock:
        controller._window_visible = True
        generation = controller._navigation_generation

    def fail_main_restore() -> None:
        raise RuntimeError("main restore failed")

    controller.bind_main_focus_callback(fail_main_restore)
    controller.hide_and_restore_main(generation, 1, lambda: True)

    assert window.actions == ["hide"]
    assert controller._window_visible is False
    controller.shutdown()


def test_fd_work_main_restore_is_owned_by_desktop_shell():
    source = (
        Path(__file__).resolve().parents[1] / "worktrace" / "webview_main.py"
    ).read_text(encoding="utf-8")

    assert "fd_work_controller.bind_main_focus_callback(shell.show_window)" in source
    assert 'for action in ("show", "restore", "focus")' not in source


def test_windows_acceptance_rejects_binding_without_helper_foreground(monkeypatch, tmp_path):
    state = {
        "helper_foreground_count": 0,
    }
    writes = []
    monkeypatch.setattr(acceptance, "_read_json", lambda _path: state)
    monkeypatch.setattr(acceptance, "_foreground_title", lambda: "WorkTrace")
    monkeypatch.setattr(
        acceptance,
        "_candidate",
        lambda _state: {
            "project_id": 1,
            "created_at": "2026-08-13T00:00:00+00:00",
            "name_hash": "hash",
        },
    )
    monkeypatch.setattr(
        acceptance,
        "_write_json",
        lambda _path, value: writes.append(dict(value)),
    )

    result = acceptance.monitor(
        SimpleNamespace(state=tmp_path / "state.json", timeout_seconds=1.0)
    )

    assert result == 1
    assert writes[-1]["monitor_error"] == "helper_never_foreground"
