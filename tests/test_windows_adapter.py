from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from worktrace.platforms import windows_path_resolver
from worktrace.platforms.windows_adapter import (
    CanonicalWindowsPathResolver,
    WindowsAdapter,
)
from worktrace.platforms.windows_path_resolver import (
    _extract_path_from_quoted_title,
    _is_valid_com_path,
    _match_open_file_path,
    _office_candidate_matches_title,
    _privacy_path_required,
    _process_matches_com_app,
    _run_with_timeout,
    resolve_title_file_path,
)

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


def test_resolve_title_file_path_preserves_windows_path():
    title = r"C:\Work\Matter A\Spec Sheet.docx - Word"
    assert resolve_title_file_path(title) == r"C:\Work\Matter A\Spec Sheet.docx"


def test_extract_path_from_quoted_title_uses_quoted_windows_path():
    title = 'Editing "D:\\Client\\Report.xlsx" - Excel'
    assert _extract_path_from_quoted_title(title) == r"D:\Client\Report.xlsx"


def test_match_open_file_path_requires_unique_basename_match():
    assert _match_open_file_path(
        "Report.docx",
        [r"C:\A\Report.docx", r"C:\B\Other.docx"],
    ) == r"C:\A\Report.docx"
    assert _match_open_file_path(
        "Report.docx",
        [r"C:\A\Report.docx", r"C:\B\Report.docx"],
    ) is None


def test_office_candidate_title_matching_is_case_insensitive():
    assert _office_candidate_matches_title(
        r"C:\Client\Quarterly Report.xlsx",
        "quarterly report.xlsx - excel",
    )
    assert not _office_candidate_matches_title(
        r"C:\Client\Other.xlsx",
        "quarterly report.xlsx - excel",
    )


def test_process_matches_only_supported_com_application():
    assert _process_matches_com_app("WINWORD.EXE", "word")
    assert _process_matches_com_app("excel.exe", "excel")
    assert not _process_matches_com_app("notepad.exe", "word")


def test_com_path_validation_rejects_urls_and_non_paths():
    assert _is_valid_com_path(r"C:\Client\Report.docx")
    assert not _is_valid_com_path("https://example.com/report.docx")
    assert not _is_valid_com_path("Report.docx")


def test_privacy_path_requirement_is_explicit_for_supported_apps():
    assert _privacy_path_required("WINWORD.EXE", "Report.docx - Word")
    assert _privacy_path_required("Code.exe", "main.py - Visual Studio Code")
    assert not _privacy_path_required("notepad.exe", "Notes")


def test_timeout_helper_returns_none_when_resolver_exceeds_budget():
    def slow():
        time.sleep(0.05)
        return "late"

    started = time.monotonic()
    assert _run_with_timeout(slow, 0.005) is None
    assert time.monotonic() - started < 0.04


def test_canonical_resolver_uses_pure_index_after_live_sources_miss(monkeypatch):
    resolver = CanonicalWindowsPathResolver(
        com_paths=lambda _process_name: [],
        open_file_paths=lambda _pid: [],
        cache_seconds=0,
    )
    calls: list[tuple[str, bool]] = []

    def pure_lookup(title, *, include_excluded=True):
        calls.append((title, include_excluded))
        return r"D:\Repo\main.py"

    monkeypatch.setattr(
        "worktrace.platforms.windows_adapter.resolve_unique_path_from_title",
        pure_lookup,
    )

    result = resolver.resolve(
        (10, 9001, "Code.exe", "main.py - Visual Studio Code"),
        "Code.exe",
        "main.py - Visual Studio Code",
        9001,
    )

    assert result == r"D:\Repo\main.py"
    assert calls == [("main.py - Visual Studio Code", True)]


def test_canonical_resolver_negative_cache_avoids_repeated_live_resolution(monkeypatch):
    calls = {"com": 0, "open": 0, "index": 0}

    def com_paths(_process_name):
        calls["com"] += 1
        return []

    def open_paths(_pid):
        calls["open"] += 1
        return []

    resolver = CanonicalWindowsPathResolver(
        com_paths=com_paths,
        open_file_paths=open_paths,
        cache_seconds=60,
        negative_cache_seconds=60,
    )

    def no_index(*args, **kwargs):
        calls["index"] += 1
        return None

    monkeypatch.setattr(
        "worktrace.platforms.windows_adapter.resolve_unique_path_from_title",
        no_index,
    )
    key = (10, 9001, "Code.exe", "main.py - Visual Studio Code")

    assert resolver.resolve(key, "Code.exe", "main.py - Visual Studio Code", 9001) is None
    assert resolver.resolve(key, "Code.exe", "main.py - Visual Studio Code", 9001) is None
    assert calls == {"com": 1, "open": 1, "index": 1}


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
    monkeypatch.setattr(adapter._clipboard, "set_enabled", lambda value: calls.append(value))
    monkeypatch.setattr(adapter._clipboard, "clear", lambda: calls.append("clear"))
    monkeypatch.setattr(adapter._clipboard, "shutdown", lambda: calls.append("shutdown"))

    adapter.reset_runtime_state()
    adapter.shutdown()

    assert calls == [False, "clear", "shutdown"]
    assert resolver.reset_calls == 2


def test_base_resolver_module_is_not_the_runtime_adapter_owner():
    assert not hasattr(windows_path_resolver, "WindowsAdapter")
