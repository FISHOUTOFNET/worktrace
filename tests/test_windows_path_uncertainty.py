from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from worktrace.platforms.windows_adapter import WindowsAdapter

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


def test_adapter_marks_failed_authoritative_probe_as_privacy_uncertain(monkeypatch):
    class Resolver:
        def should_probe_path(self, process_name, title):
            assert process_name == "WINWORD.EXE"
            assert title == "Confidential - Word"
            return True

        def privacy_path_required(self, process_name, title):
            return False

        def resolve(self, window_key, process_name, title, pid):
            assert window_key == (101, 42, "WINWORD.EXE", "Confidential - Word")
            return None

        def reset(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(
            GetForegroundWindow=lambda: 101,
            GetWindowText=lambda _hwnd: "Confidential - Word",
            GetClassName=lambda _hwnd: "OpusApp",
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda _hwnd: (1, 42)),
    )

    class FakeProcess:
        def name(self):
            return "WINWORD.EXE"

    class FakePsutilError(Exception):
        pass

    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Process=lambda _pid: FakeProcess(), Error=FakePsutilError),
    )
    monkeypatch.setattr(
        "worktrace.platforms.windows_adapter.resolve_title_file_path",
        lambda _title: None,
    )

    adapter = WindowsAdapter(path_resolver=Resolver())
    adapter._clipboard.shutdown()
    active = adapter.get_active_window()

    assert active.file_path_hint is None
    assert active.privacy_path_required is False
    assert active.path_resolution_uncertain is True


def test_adapter_does_not_mark_successful_probe_as_uncertain(monkeypatch):
    class Resolver:
        def should_probe_path(self, _process_name, _title):
            return True

        def privacy_path_required(self, _process_name, _title):
            return False

        def resolve(self, *_args):
            return r"D:\Matter\Confidential.docx"

        def reset(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(
            GetForegroundWindow=lambda: 101,
            GetWindowText=lambda _hwnd: "Confidential - Word",
            GetClassName=lambda _hwnd: "OpusApp",
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda _hwnd: (1, 42)),
    )

    class FakeProcess:
        def name(self):
            return "WINWORD.EXE"

    class FakePsutilError(Exception):
        pass

    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Process=lambda _pid: FakeProcess(), Error=FakePsutilError),
    )
    monkeypatch.setattr(
        "worktrace.platforms.windows_adapter.resolve_title_file_path",
        lambda _title: None,
    )

    adapter = WindowsAdapter(path_resolver=Resolver())
    adapter._clipboard.shutdown()
    active = adapter.get_active_window()

    assert active.file_path_hint == r"D:\Matter\Confidential.docx"
    assert active.path_resolution_uncertain is False
