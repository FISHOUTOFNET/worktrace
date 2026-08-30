from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import pytest

from worktrace.collector import collector as collector_mod
from worktrace.collector.collector import run_collector
from worktrace.platforms.windows_adapter import WindowsAdapter
from worktrace.services import privacy_gate_service, settings_service

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime]


class _Resolver:
    def privacy_path_required(self, _process_name, _title):
        return False

    def resolve(self, *_args):
        return None

    def reset(self):
        return None


def test_windows_foreground_absence_is_not_an_adapter_failure(monkeypatch):
    class PsutilError(Exception):
        pass

    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Error=PsutilError, Process=lambda _pid: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(GetForegroundWindow=lambda: 0),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda _hwnd: (0, 0)),
    )

    adapter = WindowsAdapter(path_resolver=_Resolver())
    assert adapter.get_active_window() is None


class _IdleAdapter:
    def __init__(self) -> None:
        self.active_calls = 0
        self.idle_calls = 0
        self.clipboard_calls = 0

    def get_active_window(self):
        self.active_calls += 1
        raise AssertionError("foreground sampling must be skipped once idle is known")

    def get_idle_seconds(self):
        self.idle_calls += 1
        return 60

    def get_clipboard_events(self):
        self.clipboard_calls += 1
        raise AssertionError("clipboard drain must be skipped while idle")

    def set_clipboard_capture_enabled(self, _enabled: bool) -> None:
        return None


class _NoForegroundAdapter:
    def __init__(self) -> None:
        self.active_calls = 0
        self.idle_calls = 0
        self.clipboard_calls = 0

    def get_active_window(self):
        self.active_calls += 1
        return None

    def get_idle_seconds(self):
        self.idle_calls += 1
        return 0

    def get_clipboard_events(self):
        self.clipboard_calls += 1
        return []

    def set_clipboard_capture_enabled(self, _enabled: bool) -> None:
        return None


def _stop_after_one_poll(monkeypatch, stop_event):
    def fake_sleep(_stop_event, _control, next_poll_deadline):
        stop_event.set()
        return next_poll_deadline + 1.0

    monkeypatch.setattr(collector_mod, "_sleep_until_next_poll", fake_sleep)


def test_idle_short_circuits_foreground_and_clipboard_sampling(temp_db, monkeypatch):
    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("idle_threshold_seconds", "1")
    stop_event = threading.Event()
    adapter = _IdleAdapter()
    _stop_after_one_poll(monkeypatch, stop_event)

    run_collector(adapter, stop_event)

    assert adapter.idle_calls == 1
    assert adapter.active_calls == 0
    assert adapter.clipboard_calls == 0


def test_no_foreground_window_is_a_normal_observation_gap(temp_db, monkeypatch):
    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("idle_threshold_seconds", "300")
    stop_event = threading.Event()
    adapter = _NoForegroundAdapter()
    _stop_after_one_poll(monkeypatch, stop_event)

    run_collector(adapter, stop_event)

    assert adapter.idle_calls == 1
    assert adapter.active_calls == 1
    assert adapter.clipboard_calls == 0
    assert settings_service.get_setting("collector_consecutive_failures") == "0"
