import sys
import threading
from types import SimpleNamespace

from worktrace.platforms import windows_adapter
from worktrace.platforms.windows_adapter import (
    _all_com_catalog_entries,
    _com_candidates,
    _ensure_com_initialized,
    _evaluate_com_path_expression,
    _is_valid_com_path,
    _match_open_file_path,
    _normalize_com_file_path,
    _office_candidates,
    _resolve_active_file_path,
    _uninitialize_com,
)


def test_office_com_path_is_discarded_when_title_is_unrelated():
    assert not _is_valid_com_path("D:\\CaseA\\Spec.docx", "Budget.xlsx - Excel")


def test_office_com_path_is_accepted_when_title_matches_file_name():
    assert _is_valid_com_path("D:\\CaseA\\Spec.docx", "Spec.docx - Word")


def test_com_path_accepts_non_whitelisted_extension_when_title_matches():
    assert _is_valid_com_path("D:\\Images\\hero.psd", "hero.psd - Adobe Photoshop")


def test_wps_candidates_include_kingsoft_prog_ids():
    candidates = _office_candidates("wps.exe")
    assert ("KWps.Application", "ActiveDocument.FullName") in candidates
    assert ("KET.Application", "ActiveWorkbook.FullName") in candidates
    assert ("KWPP.Application", "ActivePresentation.FullName") in candidates


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
    class FakeOpenFile:
        def __init__(self, path):
            self.path = path

    class FakeProcess:
        def __init__(self, _pid):
            pass

        def open_files(self):
            return [
                FakeOpenFile("C:\\Repo\\WorkTrace\\main.py"),
                FakeOpenFile("C:\\Repo\\WorkTrace\\README.md"),
            ]

    fake_psutil = SimpleNamespace(Process=FakeProcess, Error=Exception)
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(windows_adapter, "_com_candidates", lambda _process_name: [])

    assert _resolve_active_file_path("Code.exe", "main.py - Visual Studio Code", 123) == "C:\\Repo\\WorkTrace\\main.py"


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
    result = _ensure_com_initialized()
    assert result is True
    _uninitialize_com()


def test_ensure_com_initialized_succeeds_on_background_thread():
    """CoInitialize must be called explicitly on background threads.

    This is the core fix for the bug where the collector thread failed to
    resolve WPS file paths because COM was not initialized.
    """
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
    """_resolve_active_file_path must work from a background thread.

    The collector runs on a daemon thread.  Without CoInitialize the COM
    lookup silently fails and file_path_hint stays None, causing activities
    to be misclassified as uncategorized.
    """
    com_init_called = [False]
    original_ensure = _ensure_com_initialized
    original_uninit = _uninitialize_com

    def _fake_ensure():
        com_init_called[0] = True
        return original_ensure()

    monkeypatch.setattr(windows_adapter, "_ensure_com_initialized", _fake_ensure)
    monkeypatch.setattr(windows_adapter, "_uninitialize_com", original_uninit)

    # No COM candidates, no open files -> returns None, but COM init must still be attempted
    monkeypatch.setattr(windows_adapter, "_com_candidates", lambda _pn: [])

    bg_result = [None]

    def _worker():
        bg_result[0] = _resolve_active_file_path("wps.exe", "doc.docx - WPS Office", 1234)

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=10)

    assert com_init_called[0] is True, "COM should be initialized even on background threads"


def test_uninitialize_com_is_balanced_after_resolve(monkeypatch):
    """After _resolve_active_file_path completes, COM init/uninit must be balanced."""
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
    monkeypatch.setattr(windows_adapter, "_com_candidates", lambda _pn: [])

    _resolve_active_file_path("wps.exe", "doc.docx - WPS Office")

    # If COM was initialized, uninit must have been called the same number of times
    if init_count[0] > 0:
        assert uninit_count[0] == init_count[0], "CoInitialize/CoUninitialize calls must be balanced"
