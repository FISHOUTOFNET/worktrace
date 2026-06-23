from __future__ import annotations

import ctypes
import json
import logging
import ntpath
import re
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from urllib.parse import unquote, urlparse

from .. import config
from ..activity_identity import extract_anchor_file_name, extract_file_name_from_title
from ..constants import TIME_FORMAT
from ..path_utils import (
    extract_file_path_from_title,
    looks_like_local_file_path,
    normalize_path_key,
    split_file_path,
)
from .base import ActiveWindow, ClipboardTextEvent


@dataclass(frozen=True)
class ComPathCatalogEntry:
    name: str
    process_names: tuple[str, ...]
    prog_ids: tuple[str, ...]
    path_expressions: tuple[str, ...]


def _versioned_prog_ids(base: str, start: int, end: int) -> tuple[str, ...]:
    return tuple([base, *[f"{base}.{version}" for version in range(end, start - 1, -1)]])


_BUILTIN_COM_PATH_CATALOG: tuple[ComPathCatalogEntry, ...] = (
    ComPathCatalogEntry("Microsoft Word", ("winword.exe", "winword"), ("Word.Application",), ("ActiveDocument.FullName",)),
    ComPathCatalogEntry("Microsoft Excel", ("excel.exe", "excel"), ("Excel.Application",), ("ActiveWorkbook.FullName",)),
    ComPathCatalogEntry(
        "Microsoft PowerPoint",
        ("powerpnt.exe", "powerpnt"),
        ("PowerPoint.Application",),
        ("ActivePresentation.FullName",),
    ),
    ComPathCatalogEntry("Microsoft Visio", ("visio.exe", "visio"), ("Visio.Application",), ("ActiveDocument.FullName",)),
    ComPathCatalogEntry(
        "Microsoft Publisher",
        ("mspub.exe", "mspub"),
        ("Publisher.Application",),
        ("ActiveDocument.FullName",),
    ),
    ComPathCatalogEntry(
        "Microsoft Access",
        ("msaccess.exe", "msaccess"),
        ("Access.Application",),
        ("CurrentProject.FullName",),
    ),
    ComPathCatalogEntry(
        "Microsoft Project",
        ("winproj.exe", "winproj"),
        ("MSProject.Application",),
        ("ActiveProject.FullName",),
    ),
    ComPathCatalogEntry(
        "WPS Writer",
        ("wps.exe", "wps", "kwps.exe", "kwps"),
        ("KWps.Application", "kwps.Application", "wps.Application"),
        ("ActiveDocument.FullName",),
    ),
    ComPathCatalogEntry(
        "WPS Spreadsheets",
        ("wps.exe", "wps", "et.exe", "et", "ket.exe", "ket"),
        ("KET.Application", "ket.Application", "et.Application"),
        ("ActiveWorkbook.FullName",),
    ),
    ComPathCatalogEntry(
        "WPS Presentation",
        ("wps.exe", "wps", "wpp.exe", "wpp", "kwpp.exe", "kwpp"),
        ("KWPP.Application", "kwpp.Application", "wpp.Application"),
        ("ActivePresentation.FullName",),
    ),
    ComPathCatalogEntry(
        "Adobe Acrobat",
        ("acrobat.exe", "acrobat", "acrord32.exe", "acrord32"),
        ("AcroExch.App", "AcroExch.App.1"),
        ("GetActiveDoc().GetPDDoc().GetJSObject().path",),
    ),
    ComPathCatalogEntry(
        "AutoCAD",
        ("acad.exe", "acad", "acadlt.exe", "acadlt"),
        _versioned_prog_ids("AutoCAD.Application", 17, 30),
        ("ActiveDocument.FullName",),
    ),
    ComPathCatalogEntry(
        "Adobe Photoshop",
        ("photoshop.exe", "photoshop"),
        ("Photoshop.Application",),
        ("ActiveDocument.FullName",),
    ),
    ComPathCatalogEntry(
        "Adobe Illustrator",
        ("illustrator.exe", "illustrator"),
        ("Illustrator.Application",),
        ("ActiveDocument.FullName",),
    ),
    ComPathCatalogEntry(
        "Adobe InDesign",
        ("indesign.exe", "indesign"),
        ("InDesign.Application",),
        ("ActiveDocument.FullName",),
    ),
    ComPathCatalogEntry(
        "CorelDRAW",
        ("coreldrw.exe", "coreldrw", "coreldraw.exe", "coreldraw"),
        _versioned_prog_ids("CorelDRAW.Application", 17, 30),
        ("ActiveDocument.FullFileName",),
    ),
    ComPathCatalogEntry(
        "SOLIDWORKS",
        ("sldworks.exe", "sldworks"),
        ("SldWorks.Application",),
        ("ActiveDoc.GetPathName()",),
    ),
)


_COM_CALL_TIMEOUT_SECONDS = 2.0
_OPEN_FILES_TIMEOUT_SECONDS = 2.0
_COM_FAILURE_COOLDOWN_SECONDS = 30.0
_OPEN_FILES_FAILURE_COOLDOWN_SECONDS = 30.0

_com_failure_times: dict[str, float] = {}
_open_files_failure_times: dict[int, float] = {}


def _is_com_available(prog_id: str) -> bool:
    last_fail = _com_failure_times.get(prog_id)
    if last_fail is None:
        return True
    return time.monotonic() - last_fail > _COM_FAILURE_COOLDOWN_SECONDS


def _mark_com_failed(prog_id: str) -> None:
    _com_failure_times[prog_id] = time.monotonic()


def _is_open_files_available(pid: int) -> bool:
    last_fail = _open_files_failure_times.get(pid)
    if last_fail is None:
        return True
    return time.monotonic() - last_fail > _OPEN_FILES_FAILURE_COOLDOWN_SECONDS


def _mark_open_files_failed(pid: int) -> None:
    _open_files_failure_times[pid] = time.monotonic()


def _run_with_timeout(func, timeout_seconds: float, *args):
    """Run *func* in a daemon thread and wait up to *timeout_seconds*.

    Returns the function result.  Raises ``TimeoutError`` if the call
    does not finish in time (the background thread is left running as a
    daemon and will be cleaned up on process exit).  Any exception raised
    by *func* is re-raised in the caller.
    """
    result_box: list = [None]
    exc_box: list = [None]
    done = threading.Event()

    def _worker():
        try:
            result_box[0] = func(*args)
        except Exception as exc:
            exc_box[0] = exc
        finally:
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    if not done.wait(timeout=timeout_seconds):
        raise TimeoutError(f"call timed out after {timeout_seconds:.1f}s")
    if exc_box[0] is not None:
        raise exc_box[0]
    return result_box[0]


class WindowsAdapter:
    def __init__(self) -> None:
        self._clipboard_monitor = _ClipboardMonitor()

    def get_active_window(self) -> ActiveWindow:
        return _get_foreground_active_window()

    def get_idle_seconds(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        last_input = LASTINPUTINFO()
        last_input.cbSize = ctypes.sizeof(last_input)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input)):
            return 0
        tick_count = ctypes.windll.kernel32.GetTickCount()
        return int((tick_count - last_input.dwTime) / 1000)

    def get_clipboard_events(self) -> list[ClipboardTextEvent]:
        return self._clipboard_monitor.drain()


class _ClipboardMonitor:
    def __init__(self) -> None:
        self._events: deque[ClipboardTextEvent] = deque()
        self._lock = threading.Lock()
        self._started = False
        self._last_sequence: int | None = None

    def drain(self) -> list[ClipboardTextEvent]:
        self._ensure_started()
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events

    def _ensure_started(self) -> None:
        if self._started:
            return
        self._started = True
        thread = threading.Thread(target=self._run, name="WorkTraceClipboardMonitor", daemon=True)
        thread.start()

    def _run(self) -> None:
        while True:
            try:
                sequence = _clipboard_sequence_number()
                if sequence is None:
                    time.sleep(0.25)
                    continue
                if self._last_sequence is None:
                    self._last_sequence = sequence
                    time.sleep(0.25)
                    continue
                if sequence != self._last_sequence:
                    self._last_sequence = sequence
                    self._capture(sequence)
            except Exception:
                logging.debug("clipboard monitor loop failed", exc_info=True)
            time.sleep(0.25)

    def _capture(self, sequence: int) -> None:
        text = _read_clipboard_unicode_text()
        if not text:
            return
        event = ClipboardTextEvent(
            text=text,
            source_window=_get_foreground_active_window(),
            copied_at=datetime.now().strftime(TIME_FORMAT),
            sequence_number=sequence,
        )
        with self._lock:
            self._events.append(event)


def _get_foreground_active_window() -> ActiveWindow:
    import win32gui
    import win32process

    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd) or ""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process_name = ""
    app_name = ""
    import psutil

    try:
        process = psutil.Process(pid)
        process_name = process.name()
        app_name = process_name
    except psutil.Error:
        process_name = "unknown"
        app_name = "unknown"
    file_path_hint = _resolve_active_file_path(process_name, title, pid)
    window_class = None
    try:
        window_class = win32gui.GetClassName(hwnd) or None
    except Exception:
        pass
    return ActiveWindow(
        app_name=app_name,
        process_name=process_name,
        window_title=title,
        file_path_hint=file_path_hint,
        pid=pid,
        hwnd=hwnd,
        window_class=window_class,
    )


def _clipboard_sequence_number() -> int | None:
    try:
        import win32clipboard

        return int(win32clipboard.GetClipboardSequenceNumber())
    except Exception:
        logging.debug("clipboard sequence read failed", exc_info=True)
        return None


def _read_clipboard_unicode_text() -> str | None:
    opened = False
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        opened = True
        if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return None
        value = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        text = str(value or "")
        return text if text else None
    except Exception:
        logging.debug("clipboard text read failed", exc_info=True)
        return None
    finally:
        if opened:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass


def _ensure_com_initialized() -> bool:
    """Initialize COM for the current thread if not already done.

    COM operations (e.g. GetActiveObject) require CoInitialize on each thread.
    The collector runs on a background thread where COM is not auto-initialized,
    so we must call it explicitly before any COM access.  CoInitialize is
    reference-counted, so calling it multiple times is safe.
    """
    try:
        import pythoncom

        pythoncom.CoInitialize()
        return True
    except Exception:
        logging.debug("COM CoInitialize failed", exc_info=True)
        return False


def _uninitialize_com() -> None:
    """Balance a previous CoInitialize call on the current thread."""
    try:
        import pythoncom

        pythoncom.CoUninitialize()
    except Exception:
        pass


def _resolve_active_file_path(process_name: str, window_title: str, pid: int | None = None) -> str | None:
    try:
        title_path = extract_file_path_from_title(window_title)
        if title_path and looks_like_local_file_path(title_path):
            logging.debug("active file path resolved from window title")
            return split_file_path(title_path)[0]
    except Exception:
        logging.debug("active file path title parse failed", exc_info=True)

    for prog_id, expression in _com_candidates(process_name):
        if not _is_com_available(prog_id):
            continue
        try:
            path = _run_with_timeout(
                _get_com_file_path_threadsafe, _COM_CALL_TIMEOUT_SECONDS,
                prog_id, expression,
            )
            if _is_valid_com_path(path, window_title):
                logging.debug("active file path resolved from com catalog")
                return split_file_path(path)[0]
        except TimeoutError:
            _mark_com_failed(prog_id)
            logging.debug("active file path com lookup timed out for %s", prog_id)
        except Exception:
            logging.debug("active file path com lookup failed", exc_info=True)

    fallback = _resolve_open_file_path(pid, window_title)
    if fallback:
        logging.debug("active file path resolved from process open files")
        return fallback
    indexed = _resolve_indexed_file_path(window_title)
    if indexed:
        logging.debug("active file path resolved from folder rule index")
        return indexed
    return None


def _office_candidates(process_name: str) -> list[tuple[str, str]]:
    office_names = {
        "Microsoft Word",
        "Microsoft Excel",
        "Microsoft PowerPoint",
        "WPS Writer",
        "WPS Spreadsheets",
        "WPS Presentation",
    }
    return [
        (prog_id, expression)
        for entry in _BUILTIN_COM_PATH_CATALOG
        if entry.name in office_names and _process_matches_entry(process_name, entry)
        for prog_id in entry.prog_ids
        for expression in entry.path_expressions
    ]


def _com_candidates(process_name: str) -> list[tuple[str, str]]:
    return [
        (prog_id, expression)
        for entry in _all_com_catalog_entries()
        if _process_matches_entry(process_name, entry)
        for prog_id in entry.prog_ids
        if _is_registered_prog_id(prog_id)
        for expression in entry.path_expressions
    ]


def _get_com_file_path(prog_id: str, path_expression: str) -> str | None:
    import win32com.client

    app = win32com.client.GetActiveObject(prog_id)
    value = _evaluate_com_path_expression(app, path_expression)
    return _normalize_com_file_path(value)


def _get_com_file_path_threadsafe(prog_id: str, path_expression: str) -> str | None:
    """COM call wrapper that initializes/cleans up COM on the calling thread."""
    _ensure_com_initialized()
    try:
        return _get_com_file_path(prog_id, path_expression)
    finally:
        _uninitialize_com()


def _evaluate_com_path_expression(app, path_expression: str):
    value = app
    for raw_step in path_expression.split("."):
        step = raw_step.strip()
        if not step:
            return None
        if step.endswith("()"):
            value = getattr(value, step[:-2])()
        else:
            value = getattr(value, step)
        if value is None:
            return None
    return value


def _is_valid_com_path(path: str | None, window_title: str | None) -> bool:
    if not path or not looks_like_local_file_path(path):
        return False
    title = (window_title or "").casefold()
    if not title:
        return False

    full_path, _, file_stem = split_file_path(path)
    file_name = ntpath.basename(full_path)
    if file_name.casefold() in title or file_stem.casefold() in title:
        return True

    title_path = extract_file_path_from_title(window_title)
    if title_path and normalize_path_key(title_path) == normalize_path_key(full_path):
        return True

    title_file = extract_file_name_from_title(window_title)
    return bool(title_file and title_file.casefold() == file_name.casefold())


def _resolve_open_file_path(pid: int | None, window_title: str | None) -> str | None:
    if pid is None:
        return None
    title_file = extract_file_name_from_title(window_title) or extract_anchor_file_name(window_title)
    if not title_file:
        return None
    if not _is_open_files_available(pid):
        return None

    try:
        paths = _get_process_open_file_paths(pid)
    except TimeoutError:
        _mark_open_files_failed(pid)
        logging.debug("active file path open-files lookup timed out")
        return None
    except Exception:
        logging.debug("active file path open-files lookup failed", exc_info=True)
        return None
    return _match_open_file_path(title_file, paths)


def _resolve_indexed_file_path(window_title: str | None) -> str | None:
    try:
        from ..services.folder_index_service import resolve_unique_path_from_title

        return resolve_unique_path_from_title(window_title, include_excluded=True)
    except Exception:
        logging.debug("active file path folder index lookup failed", exc_info=True)
        return None


def _get_process_open_file_paths(pid: int) -> list[str]:
    if sys.platform.startswith("win"):
        return _get_process_open_file_paths_subprocess(pid)

    import psutil

    return [item.path for item in psutil.Process(pid).open_files()]


def _get_process_open_file_paths_subprocess(pid: int) -> list[str]:
    helper_cmd = _open_files_helper_cmd()
    if helper_cmd is None:
        logging.debug("active file path open-files helper not available")
        return []

    startupinfo = None
    creationflags = 0
    if sys.platform.startswith("win"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        completed = subprocess.run(
            [*helper_cmd, str(pid)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_OPEN_FILES_TIMEOUT_SECONDS,
            startupinfo=startupinfo,
            creationflags=creationflags,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"open-files helper timed out after {_OPEN_FILES_TIMEOUT_SECONDS:.1f}s") from exc

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"open-files helper failed: {message}")

    raw = json.loads(completed.stdout or "[]")
    if not isinstance(raw, list):
        return []
    return [str(path) for path in raw if str(path or "").strip()]


def _open_files_helper_cmd() -> list[str] | None:
    """Return the command prefix for the open-files helper subprocess.

    In a frozen (PyInstaller) build the main executable re-enters itself
    with ``--open-files-helper`` so the bundled Python interpreter runs
    the helper module.  This avoids the problem that ``WorkTrace.exe -c
    script`` is invalid.

    In a normal (non-frozen) environment we use ``-m`` to invoke the
    standalone helper module.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--open-files-helper"]

    # Non-frozen: use the standalone helper module.
    return [sys.executable, "-m", "worktrace.platforms.open_files_helper"]


def _match_open_file_path(title_file: str, paths: list[str]) -> str | None:
    matches: dict[str, str] = {}
    title_key = title_file.casefold()
    for path in paths:
        if not looks_like_local_file_path(path):
            continue
        full_path, _, _ = split_file_path(path)
        if ntpath.basename(full_path).casefold() == title_key:
            matches[normalize_path_key(full_path)] = full_path
    if len(matches) != 1:
        return None
    return next(iter(matches.values()))


@lru_cache(maxsize=1)
def _all_com_catalog_entries() -> tuple[ComPathCatalogEntry, ...]:
    return (*_BUILTIN_COM_PATH_CATALOG, *_load_user_com_catalog_entries())


def _load_user_com_catalog_entries() -> tuple[ComPathCatalogEntry, ...]:
    catalog_path = config.resolve_paths().base_dir / "com_path_catalog.json"
    if not catalog_path.exists():
        return ()
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        logging.debug("failed to load user com path catalog", exc_info=True)
        return ()

    raw_entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(raw_entries, list):
        logging.debug("user com path catalog must be a list or contain an entries list")
        return ()

    entries: list[ComPathCatalogEntry] = []
    for raw_entry in raw_entries:
        try:
            entries.append(_coerce_com_catalog_entry(raw_entry))
        except ValueError:
            logging.debug("invalid user com path catalog entry skipped", exc_info=True)
    return tuple(entries)


def _coerce_com_catalog_entry(raw_entry) -> ComPathCatalogEntry:
    if not isinstance(raw_entry, dict):
        raise ValueError("entry must be an object")
    name = str(raw_entry.get("name") or "User COM entry").strip()
    process_names = _coerce_string_tuple(raw_entry.get("process_names"))
    prog_ids = _coerce_string_tuple(raw_entry.get("prog_ids"))
    path_expressions = _coerce_string_tuple(raw_entry.get("path_expressions"))
    if not process_names or not prog_ids or not path_expressions:
        raise ValueError("entry requires process_names, prog_ids, and path_expressions")
    return ComPathCatalogEntry(
        name=name or "User COM entry",
        process_names=process_names,
        prog_ids=prog_ids,
        path_expressions=path_expressions,
    )


def _coerce_string_tuple(value) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return ()
    return tuple(str(item).strip() for item in items if str(item).strip())


def _process_matches_entry(process_name: str, entry: ComPathCatalogEntry) -> bool:
    process_keys = _process_name_keys(process_name)
    return any(process_keys & _process_name_keys(alias) for alias in entry.process_names)


def _process_name_keys(process_name: str) -> set[str]:
    normalized = ntpath.basename(str(process_name or "").strip()).casefold()
    if not normalized:
        return set()
    stem = ntpath.splitext(normalized)[0]
    return {normalized, stem}


@lru_cache(maxsize=None)
def _is_registered_prog_id(prog_id: str) -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\CLSID"):
            return True
    except OSError:
        return False


def _normalize_com_file_path(value) -> str | None:
    path = str(value or "").strip().strip("\"'“”‘’")
    if not path:
        return None
    path = _file_url_to_windows_path(path) or path
    path = _acrobat_device_path_to_windows_path(path) or path
    return path


def _file_url_to_windows_path(path: str) -> str | None:
    if not path.casefold().startswith("file:"):
        return None
    parsed = urlparse(path)
    decoded = unquote(parsed.path or "")
    if re.match(r"^/[A-Za-z]:/", decoded):
        decoded = decoded[1:]
    if parsed.netloc:
        decoded = f"//{parsed.netloc}{decoded}"
    return decoded.replace("/", "\\")


def _acrobat_device_path_to_windows_path(path: str) -> str | None:
    if re.match(r"^/[A-Za-z]/", path):
        return f"{path[1]}:{path[2:]}".replace("/", "\\")
    if path.startswith("//"):
        return "\\\\" + path[2:].replace("/", "\\")
    return None
