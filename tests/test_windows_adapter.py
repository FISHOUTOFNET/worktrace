from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from worktrace.platforms import windows_path_resolver
from worktrace.platforms.windows_adapter import WindowsAdapter
from worktrace.platforms.windows_path_resolver import (
    _is_valid_com_path,
    _match_open_file_path,
    resolve_title_file_path,
)

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


def test_resolve_title_file_path_preserves_windows_path():
    title = r"C:\Work\Matter A\Spec Sheet.docx - Word"
    assert resolve_title_file_path(title) == r"C:\Work\Matter A\Spec Sheet.docx"


def test_match_open_file_path_requires_unique_basename_match():
    assert _match_open_file_path(
        "Report.docx",
        [r"C:\A\Report.docx", r"C:\B\Other.docx"],
    ) == r"C:\A\Report.docx"
    assert _match_open_file_path(
        "Report.docx",
        [r"C:\A\Report.docx", r"C:\B\Report.docx"],
    ) is None


def test_com_path_validation_rejects_urls_and_non_paths():
    assert _is_valid_com_path(r"C:\Client\Report.docx", "Report.docx - Word")
    assert not _is_valid_com_path(
        "https://example.com/report.docx", "Report.docx - Word"
    )
    assert not _is_valid_com_path("Report.docx", "Report.docx - Word")


def test_adapter_builds_active_window_with_injected_resolver(monkeypatch):
    class Resolver:
        def __init__(self):
            self.reset_calls = 0

        def privacy_path_required(self, process_name, title):
            assert process_name == "WINWORD.EXE"
            assert title == "Report.docx - Word"
            return True

        def resolve(self, window_key, process_name, title, pid):
            assert window_key == (101, 42, "WINWORD.EXE", "Report.docx - Word")
            return r"D:\Client\Report.docx"

        def reset(self):
            self.reset_calls += 1

    resolver = Resolver()
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(
            GetForegroundWindow=lambda: 101,
            GetWindowText=lambda _hwnd: "Report.docx - Word",
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

    adapter = WindowsAdapter(path_resolver=resolver)
    adapter._clipboard.shutdown()
    active = adapter.get_active_window()

    assert active.app_name == "WINWORD.EXE"
    assert active.process_name == "WINWORD.EXE"
    assert active.file_path_hint == r"D:\Client\Report.docx"
    assert active.pid == 42
    assert active.hwnd == 101
    assert active.window_class == "OpusApp"
    assert active.privacy_path_required is True


def test_adapter_reset_and_shutdown_clear_owned_components(monkeypatch):
    resolver = SimpleNamespace(reset_calls=0)

    def reset():
        resolver.reset_calls += 1

    resolver.reset = reset
    resolver.privacy_path_required = lambda *_args: False
    resolver.resolve = lambda *_args: None
    adapter = WindowsAdapter(path_resolver=resolver)
    calls: list[object] = []
    monkeypatch.setattr(adapter._clipboard, "reset", lambda: calls.append("reset"))
    monkeypatch.setattr(adapter._clipboard, "shutdown", lambda: calls.append("shutdown"))

    adapter.reset_runtime_state()
    adapter.shutdown()

    assert calls == ["reset", "shutdown"]
    assert resolver.reset_calls == 2


def test_base_resolver_module_is_not_the_runtime_adapter_owner():
    assert not hasattr(windows_path_resolver, "WindowsAdapter")
