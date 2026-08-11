from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from worktrace.collector.collector_failure_policy import (
    CollectorFailureCode,
    classify_collector_failure,
)
from worktrace.platforms.base import PlatformTemporarilyUnavailableError
from worktrace.platforms.windows_adapter import WindowsAdapter

pytestmark = [pytest.mark.unit, pytest.mark.collector_runtime]


class _Resolver:
    def privacy_path_required(self, _process_name, _title):
        return False

    def resolve(self, *_args):
        return None

    def reset(self):
        return None


def _install_windows_modules(monkeypatch, *, hwnd=100, pid=200, title="Document"):
    class PsutilError(Exception):
        pass

    calls = {"process": 0}

    def process_factory(value):
        calls["process"] += 1
        return SimpleNamespace(name=lambda: f"process-{value}.exe")

    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Error=PsutilError, Process=process_factory),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(
            GetForegroundWindow=lambda: hwnd,
            GetWindowText=lambda _hwnd: title,
            GetClassName=lambda _hwnd: "WindowClass",
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda _hwnd: (1, pid)),
    )
    return calls


def test_invalid_foreground_pid_is_retryable_platform_race(monkeypatch):
    calls = _install_windows_modules(monkeypatch, pid=-135540928)
    adapter = WindowsAdapter(path_resolver=_Resolver())

    with pytest.raises(PlatformTemporarilyUnavailableError) as captured:
        adapter.get_active_window()

    assert calls["process"] == 0
    disposition = classify_collector_failure(captured.value)
    assert disposition.code is CollectorFailureCode.ADAPTER_TEMPORARILY_UNAVAILABLE
    assert disposition.retryable is True


def test_foreground_window_lookup_failure_is_retryable_platform_race(monkeypatch):
    _install_windows_modules(monkeypatch)
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(
            GetForegroundWindow=lambda: 100,
            GetWindowText=lambda _hwnd: (_ for _ in ()).throw(
                RuntimeError("window vanished")
            ),
            GetClassName=lambda _hwnd: "WindowClass",
        ),
    )
    adapter = WindowsAdapter(path_resolver=_Resolver())

    with pytest.raises(PlatformTemporarilyUnavailableError) as captured:
        adapter.get_active_window()

    disposition = classify_collector_failure(captured.value)
    assert disposition.code is CollectorFailureCode.ADAPTER_TEMPORARILY_UNAVAILABLE
    assert disposition.retryable is True


def test_valid_foreground_window_preserves_existing_projection(monkeypatch):
    calls = _install_windows_modules(monkeypatch, hwnd=321, pid=654, title="Draft")
    adapter = WindowsAdapter(path_resolver=_Resolver())

    active = adapter.get_active_window()

    assert calls["process"] == 1
    assert active.hwnd == 321
    assert active.pid == 654
    assert active.process_name == "process-654.exe"
    assert active.app_name == "process-654.exe"
    assert active.window_title == "Draft"
