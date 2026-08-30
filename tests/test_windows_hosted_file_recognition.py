from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from worktrace.platforms.windows_adapter import WindowsAdapter

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


class _Resolver:
    def __init__(self, resolved_path: str | None = None) -> None:
        self.resolved_path = resolved_path
        self.calls: list[tuple] = []
        self.reset_calls = 0

    def privacy_path_required(self, _process_name, _title):
        return False

    def should_probe_path(self, _process_name, _title):
        return False

    def resolve(self, *args):
        self.calls.append(args)
        return self.resolved_path

    def reset(self):
        self.reset_calls += 1


class _FakePsutilError(Exception):
    pass


def _install_window_modules(monkeypatch, *, processes, children=(), title="evidence.jpg - Photos"):
    def process(pid):
        name = processes.get(int(pid))
        if name is None:
            raise _FakePsutilError("missing")
        return SimpleNamespace(name=lambda: name)

    def get_pid(hwnd):
        hwnd = int(hwnd)
        if hwnd == 101:
            return 1, 42
        child_map = {int(child_hwnd): int(pid) for child_hwnd, pid in children}
        return 1, child_map[hwnd]

    def enum_children(_hwnd, callback, extra):
        for child_hwnd, _pid in children:
            callback(child_hwnd, extra)

    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(
            GetForegroundWindow=lambda: 101,
            GetWindowText=lambda _hwnd: title,
            GetClassName=lambda _hwnd: "ApplicationFrameWindow",
            EnumChildWindows=enum_children,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=get_pid),
    )
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Process=process, Error=_FakePsutilError),
    )
    monkeypatch.setattr(
        "worktrace.platforms.windows_adapter.resolve_title_file_path",
        lambda _title: None,
    )


def test_application_frame_host_uses_unique_non_host_child(monkeypatch):
    resolver = _Resolver(r"D:\Cases\evidence.jpg")
    _install_window_modules(
        monkeypatch,
        processes={42: "ApplicationFrameHost.exe", 77: "Photos.exe"},
        children=((201, 77),),
    )
    adapter = WindowsAdapter(path_resolver=resolver)
    adapter._clipboard.shutdown()

    active = adapter.get_active_window()

    assert active.pid == 77
    assert active.hwnd == 101
    assert active.process_name == "Photos.exe"
    assert active.app_name == "Photos.exe"
    assert active.file_path_hint == r"D:\Cases\evidence.jpg"
    assert active.path_resolution_uncertain is False
    assert len(resolver.calls) == 1
    assert resolver.calls[0][0] == (101, 77, "Photos.exe", "evidence.jpg - Photos")
    assert resolver.calls[0][3] == 77


def test_application_frame_host_keeps_physical_owner_when_children_are_ambiguous(monkeypatch):
    resolver = _Resolver(None)
    _install_window_modules(
        monkeypatch,
        processes={
            42: "ApplicationFrameHost.exe",
            77: "Photos.exe",
            88: "OtherPackagedApp.exe",
        },
        children=((201, 77), (202, 88)),
    )
    adapter = WindowsAdapter(path_resolver=resolver)
    adapter._clipboard.shutdown()

    active = adapter.get_active_window()

    assert active.pid == 42
    assert active.process_name == "ApplicationFrameHost.exe"
    assert active.path_resolution_uncertain is True
    assert resolver.calls[0][0][1] == 42


def test_generic_failed_path_probe_is_cooled_down(monkeypatch):
    resolver = _Resolver(None)
    _install_window_modules(
        monkeypatch,
        processes={42: "player.exe"},
        title="recording.mp4 - Player",
    )
    adapter = WindowsAdapter(path_resolver=resolver)
    adapter._clipboard.shutdown()

    first = adapter.get_active_window()
    second = adapter.get_active_window()

    assert first.path_resolution_uncertain is True
    assert second.path_resolution_uncertain is True
    assert len(resolver.calls) == 1


def test_browser_dotted_title_does_not_trigger_generic_path_probe(monkeypatch):
    resolver = _Resolver(None)
    _install_window_modules(
        monkeypatch,
        processes={42: "msedge.exe"},
        title="report.pdf - Microsoft Edge",
    )
    adapter = WindowsAdapter(path_resolver=resolver)
    adapter._clipboard.shutdown()

    active = adapter.get_active_window()

    assert active.process_name == "msedge.exe"
    assert active.path_resolution_uncertain is False
    assert resolver.calls == []
