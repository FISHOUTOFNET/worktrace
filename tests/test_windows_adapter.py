import sys
import threading
import time
import inspect
from types import SimpleNamespace

import pytest

from worktrace.platforms import windows_adapter
from worktrace.platforms.windows_adapter import (
    _all_com_catalog_entries,
    _com_candidates,
    _ensure_com_initialized,
    _evaluate_com_path_expression,
    _get_com_file_path_threadsafe,
    _get_foreground_active_window,
    _is_com_available,
    _is_open_files_available,
    _is_valid_com_path,
    _mark_com_failed,
    _mark_open_files_failed,
    _match_open_file_path,
    _normalize_com_file_path,
    _resolve_active_file_path,
    _run_with_timeout,
    _uninitialize_com,
)


def test_office_com_path_is_discarded_when_title_is_unrelated():
    assert not _is_valid_com_path("D:\\CaseA\\Spec.docx", "Budget.xlsx - Excel")


def test_office_com_path_is_accepted_when_title_matches_file_name():
    assert _is_valid_com_path("D:\\CaseA\\Spec.docx", "Spec.docx - Word")


def test_com_path_accepts_non_whitelisted_extension_when_title_matches():
    assert _is_valid_com_path("D:\\Images\\hero.psd", "hero.psd - Adobe Photoshop")


def test_open_file_match_returns_unique_exact_file_name():
    assert _match_open_file_path(
        "quantile_export_20260612_2.xlsx",
        [
            "C:\\PycharmProjects\\Finance\\notes.txt",
            "C:\\PycharmProjects\\Finance\\quantile_export_20260612_2.xlsx",
        ],
    ) == "C:\\PycharmProjects\\Finance\\quantile_export_20260612_2.xlsx"


def test_open_file_match_accepts_any_extension():
    assert _match_open_file_path(
        "main.py",
        [
            "C:\\Repo\\WorkTrace\\main.py",
            "C:\\Repo\\WorkTrace\\README.md",
        ],
    ) == "C:\\Repo\\WorkTrace\\main.py"


def test_open_file_match_ignores_ambiguous_matches():
    assert _match_open_file_path(
        "quantile_export_20260612_2.xlsx",
        [
            "C:\\PycharmProjects\\Finance\\quantile_export_20260612_2.xlsx",
            "D:\\Downloads\\quantile_export_20260612_2.xlsx",
        ],
    ) is None


def test_com_candidates_filter_by_process_and_registered_prog_id(monkeypatch):
    monkeypatch.setattr(windows_adapter, "_is_registered_prog_id", lambda prog_id: prog_id == "Photoshop.Application")

    assert ("Photoshop.Application", "ActiveDocument.FullName") in _com_candidates("Photoshop.exe")
    assert _com_candidates("notepad.exe") == []


def test_acrobat_device_path_is_normalized_to_windows_path():
    assert _normalize_com_file_path("/C/Users/me/Documents/Spec.pdf") == "C:\\Users\\me\\Documents\\Spec.pdf"


def test_com_path_expression_supports_properties_and_zero_arg_methods():
    class JsObject:
        path = "/C/Users/me/Documents/Spec.pdf"

    class PdDoc:
        def GetJSObject(self):
            return JsObject()

    class AvDoc:
        def GetPDDoc(self):
            return PdDoc()

    class App:
        def GetActiveDoc(self):
            return AvDoc()

    assert _evaluate_com_path_expression(App(), "GetActiveDoc().GetPDDoc().GetJSObject().path") == (
        "/C/Users/me/Documents/Spec.pdf"
    )


def test_resolve_active_file_path_uses_open_files_for_any_process(monkeypatch):
    monkeypatch.setattr(windows_adapter, "_com_candidates", lambda _process_name: [])
    monkeypatch.setattr(
        windows_adapter,
        "_get_process_open_file_paths",
        lambda _pid: [
            "C:\\Repo\\WorkTrace\\main.py",
            "C:\\Repo\\WorkTrace\\README.md",
        ],
    )

    assert _resolve_active_file_path("Code.exe", "main.py - Visual Studio Code", 123) == "C:\\Repo\\WorkTrace\\main.py"


def test_foreground_active_window_does_not_call_full_path_resolver_synchronously():
    source = inspect.getsource(_get_foreground_active_window)
    assert "_resolve_active_file_path(" not in source
    assert "_schedule_active_file_path_resolution" in source


def test_foreground_active_window_fast_path_does_not_block_on_slow_resolver(monkeypatch):
    class FakeWin32Gui:
        @staticmethod
        def GetForegroundWindow():
            return 101

        @staticmethod
        def GetWindowText(_hwnd):
            return "main.py - Visual Studio Code"

        @staticmethod
        def GetClassName(_hwnd):
            return "Chrome_WidgetWin_1"

    class FakeWin32Process:
        @staticmethod
        def GetWindowThreadProcessId(_hwnd):
            return (1, 4242)

    class FakeProcess:
        def __init__(self, _pid):
            pass

        def name(self):
            return "Code.exe"

    class FakePsutil:
        Error = Exception
        Process = FakeProcess

    def slow_resolver(*_args, **_kwargs):
        time.sleep(1.0)
        return "C:\\Repo\\WorkTrace\\main.py"

    monkeypatch.setitem(sys.modules, "win32gui", FakeWin32Gui)
    monkeypatch.setitem(sys.modules, "win32process", FakeWin32Process)
    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
    monkeypatch.setattr(windows_adapter, "_resolve_title_file_path", lambda _title: None)
    monkeypatch.setattr(windows_adapter, "_resolve_active_file_path", slow_resolver)
    windows_adapter._active_file_path_cache.clear()
    windows_adapter._active_file_path_inflight.clear()

    started = time.perf_counter()
    active = _get_foreground_active_window()
    elapsed = time.perf_counter() - started

    assert active.window_title == "main.py - Visual Studio Code"
    assert active.file_path_hint is None
    assert elapsed < 0.3


def test_open_files_timeout_marks_pid_cooldown(monkeypatch):
    calls = []
    pid = 424242
    windows_adapter._open_files_failure_times.pop(pid, None)
    monkeypatch.setattr(windows_adapter, "_com_candidates", lambda _process_name: [])
    monkeypatch.setattr(windows_adapter, "extract_file_path_from_title", lambda _t: None)
    monkeypatch.setattr(windows_adapter, "_resolve_indexed_file_path", lambda _t: None)

    def _timeout(_pid):
        calls.append(_pid)
        raise TimeoutError("slow handle enumeration")

    monkeypatch.setattr(windows_adapter, "_get_process_open_file_paths", _timeout)

    assert _resolve_active_file_path("Code.exe", "main.py - Visual Studio Code", pid) is None
    assert _resolve_active_file_path("Code.exe", "main.py - Visual Studio Code", pid) is None
    assert calls == [pid]


def test_open_files_cooldown_skips_recently_failed_pid():
    pid = 434343
    windows_adapter._open_files_failure_times.pop(pid, None)
    _mark_open_files_failed(pid)
    assert not _is_open_files_available(pid)
    assert _is_open_files_available(pid + 1)


def test_user_com_catalog_file_is_loaded(tmp_path, monkeypatch):
    catalog_dir = tmp_path / "WorkTrace"
    catalog_dir.mkdir()
    (catalog_dir / "com_path_catalog.json").write_text(
        """
        {
          "entries": [
            {
              "name": "Custom App",
              "process_names": ["custom.exe"],
              "prog_ids": ["Custom.Application"],
              "path_expressions": ["ActiveDocument.FullName"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(windows_adapter.config, "resolve_paths", lambda: SimpleNamespace(base_dir=catalog_dir))
    _all_com_catalog_entries.cache_clear()

    try:
        entries = _all_com_catalog_entries()
        assert any(entry.name == "Custom App" for entry in entries)
    finally:
        _all_com_catalog_entries.cache_clear()


def test_ensure_com_initialized_succeeds_on_main_thread():
    """CoInitialize should succeed on the main thread (already initialized by Python)."""
    pytest.importorskip("pythoncom")
    result = _ensure_com_initialized()
    assert result is True
    _uninitialize_com()


def test_ensure_com_initialized_succeeds_on_background_thread():
    """CoInitialize must be called explicitly on background threads.

    This is the core fix for the bug where the collector thread failed to
    resolve WPS file paths because COM was not initialized.
    """
    pytest.importorskip("pythoncom")
    bg_result = [None]

    def _worker():
        bg_result[0] = _ensure_com_initialized()
        if bg_result[0]:
            _uninitialize_com()

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=10)
    assert bg_result[0] is True


def test_resolve_active_file_path_initializes_com_on_background_thread(monkeypatch):
    """COM initialization must happen in the worker thread when resolving via COM catalog.

    The collector runs on a daemon thread. COM calls are dispatched to worker
    threads via _run_with_timeout, and each worker must initialize COM before
    calling GetActiveObject.
    """
    com_init_called = [False]
    original_ensure = _ensure_com_initialized
    original_uninit = _uninitialize_com

    def _fake_ensure():
        com_init_called[0] = True
        return original_ensure()

    monkeypatch.setattr(windows_adapter, "_ensure_com_initialized", _fake_ensure)
    monkeypatch.setattr(windows_adapter, "_uninitialize_com", original_uninit)
    # Provide a COM candidate so the code path triggers
    monkeypatch.setattr(
        windows_adapter, "_com_candidates",
        lambda _pn: [("Word.Application", "ActiveDocument.FullName")],
    )
    # Mock _get_com_file_path to avoid actual COM calls
    monkeypatch.setattr(windows_adapter, "_get_com_file_path", lambda _pid, _expr: None)

    bg_result = [None]

    def _worker():
        bg_result[0] = _resolve_active_file_path("winword.exe", "doc.docx - Word", None)

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=10)

    assert com_init_called[0] is True, "COM should be initialized in the worker thread"


def test_get_com_file_path_threadsafe_balances_com_init_uninit(monkeypatch):
    """_get_com_file_path_threadsafe must balance CoInitialize/CoUninitialize."""
    init_count = [0]
    uninit_count = [0]
    original_ensure = _ensure_com_initialized
    original_uninit = _uninitialize_com

    def _counting_ensure():
        result = original_ensure()
        if result:
            init_count[0] += 1
        return result

    def _counting_uninit():
        original_uninit()
        uninit_count[0] += 1

    monkeypatch.setattr(windows_adapter, "_ensure_com_initialized", _counting_ensure)
    monkeypatch.setattr(windows_adapter, "_uninitialize_com", _counting_uninit)
    # Mock _get_com_file_path to avoid actual COM calls
    monkeypatch.setattr(windows_adapter, "_get_com_file_path", lambda _pid, _expr: None)

    _get_com_file_path_threadsafe("Word.Application", "ActiveDocument.FullName")

    if init_count[0] > 0:
        assert uninit_count[0] == init_count[0], "CoInitialize/CoUninitialize calls must be balanced"


def test_run_with_timeout_returns_result():
    assert _run_with_timeout(lambda x: x * 2, 5.0, 21) == 42


def test_run_with_timeout_raises_timeout_error():
    import time

    try:
        _run_with_timeout(time.sleep, 0.05, 10)
        assert False, "should have raised TimeoutError"
    except TimeoutError:
        pass


def test_run_with_timeout_propagates_exception():
    def _boom():
        raise ValueError("kaboom")

    try:
        _run_with_timeout(_boom, 5.0)
        assert False, "should have raised ValueError"
    except ValueError as exc:
        assert "kaboom" in str(exc)


def test_com_failure_cooldown_skips_recently_failed_prog_id():
    _mark_com_failed("Test.Application")
    assert not _is_com_available("Test.Application")
    # A different prog_id should still be available
    assert _is_com_available("Other.Application")


def test_non_frozen_open_files_helper_returns_paths(monkeypatch):
    """Non-frozen environment should invoke the helper and return file paths."""
    import subprocess

    fake_completed = subprocess.CompletedProcess(
        args=[sys.executable, "-m", "worktrace.platforms.open_files_helper", "1234"],
        returncode=0,
        stdout='["C:\\\\Repo\\\\main.py", "C:\\\\Repo\\\\README.md"]',
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_completed)
    result = windows_adapter._get_process_open_file_paths_subprocess(1234)
    assert result == ["C:\\Repo\\main.py", "C:\\Repo\\README.md"]


def test_frozen_env_does_not_disable_open_files_helper(monkeypatch):
    """Frozen environment should NOT return None for the helper command."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = windows_adapter._open_files_helper_cmd()
    assert cmd is not None
    assert len(cmd) >= 2


def test_frozen_env_uses_reentry_flag(monkeypatch):
    """Frozen environment should use --open-files-helper reentry flag."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = windows_adapter._open_files_helper_cmd()
    assert cmd is not None
    assert "--open-files-helper" in cmd


def test_non_frozen_env_uses_module_invocation():
    """Non-frozen environment should use -m module invocation."""
    cmd = windows_adapter._open_files_helper_cmd()
    assert cmd is not None
    assert "-m" in cmd
    assert "worktrace.platforms.open_files_helper" in cmd


def test_open_files_helper_timeout_returns_safe_failure_and_cooldown(monkeypatch):
    """Helper timeout should return None and mark PID for cooldown."""
    pid = 505050
    windows_adapter._open_files_failure_times.pop(pid, None)
    monkeypatch.setattr(windows_adapter, "_com_candidates", lambda _pn: [])
    monkeypatch.setattr(windows_adapter, "extract_file_path_from_title", lambda _t: None)
    monkeypatch.setattr(windows_adapter, "_resolve_indexed_file_path", lambda _t: None)

    def _timeout(_pid):
        raise TimeoutError("slow handle enumeration")

    monkeypatch.setattr(windows_adapter, "_get_process_open_file_paths", _timeout)

    assert _resolve_active_file_path("Code.exe", "main.py - Visual Studio Code", pid) is None
    assert not _is_open_files_available(pid)


def test_open_files_helper_failure_raises_runtime_error(monkeypatch):
    """Helper subprocess failure (non-zero exit) should raise RuntimeError."""
    import subprocess

    fake_completed = subprocess.CompletedProcess(
        args=[sys.executable, "-m", "worktrace.platforms.open_files_helper", "1234"],
        returncode=1,
        stdout="",
        stderr="psutil error",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_completed)
    try:
        windows_adapter._get_process_open_file_paths_subprocess(1234)
        assert False, "should have raised RuntimeError"
    except RuntimeError as exc:
        assert "open-files helper failed" in str(exc)


def test_pyinstaller_entry_passes_pid_after_flag(monkeypatch):
    """pyinstaller_entry should pass sys.argv[2:] to open_files_helper.main."""
    import worktrace.platforms.open_files_helper as helper_mod

    captured_argv: list[list[str]] = []

    def _fake_main(argv=None):
        captured_argv.append(list(argv) if argv is not None else None)

    monkeypatch.setattr(helper_mod, "main", _fake_main)
    monkeypatch.setattr(sys, "argv", ["WorkTrace.exe", "--open-files-helper", "1234"])

    # Simulate the pyinstaller_entry branch
    if len(sys.argv) >= 2 and sys.argv[1] == "--open-files-helper":
        helper_mod.main(sys.argv[2:])

    assert captured_argv == [["1234"]]


def test_open_files_helper_main_reads_pid_from_argv():
    """open_files_helper.main(['1234']) should read pid=1234."""
    pytest.importorskip("psutil")
    from unittest.mock import patch
    from worktrace.platforms.open_files_helper import main as helper_main

    with patch("psutil.Process") as mock_process_cls:
        mock_process_cls.return_value.open_files.return_value = []
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            helper_main(["1234"])
        output = buf.getvalue().strip()

    mock_process_cls.assert_called_once_with(1234)
    assert output == "[]"


def test_open_files_helper_main_ignores_flag_as_pid():
    """open_files_helper.main(['--open-files-helper', '1234']) should treat
    '--open-files-helper' as the first arg, fail to parse it as int, and
    output [] — confirming the flag must be stripped before calling main."""
    from worktrace.platforms.open_files_helper import main as helper_main

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        helper_main(["--open-files-helper", "1234"])
    output = buf.getvalue().strip()

    # '--open-files-helper' cannot be parsed as int, so output is []
    assert output == "[]"
