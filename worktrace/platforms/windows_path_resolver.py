"""Instance-owned Windows active-document path resolution."""

from __future__ import annotations

import json
import logging
import ntpath
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import unquote, urlparse

from .. import config
from ..path_utils import (
    extract_file_path_from_title,
    looks_like_local_file_path,
    normalize_path_key,
    split_file_path,
)
from ..resources.title_parsing import (
    extract_anchor_file_name,
    extract_file_name_from_title,
)

_PATH_SUCCESS_TTL_SECONDS = 0.5
_PATH_FAILURE_TTL_SECONDS = 0.75
_MAX_PATH_CACHE = 256
_RESOLVER_CAPACITY = 2
_COM_CALL_TIMEOUT_SECONDS = 2.0
_OPEN_FILES_TIMEOUT_SECONDS = 2.0
_FAILURE_COOLDOWN_SECONDS = 30.0
_EXTRA_LOCAL_FILE_PROCESSES = {
    "code.exe",
    "devenv.exe",
    "notepad++.exe",
    "explorer.exe",
    "sublime_text.exe",
    "pycharm64.exe",
    "idea64.exe",
}


@dataclass(frozen=True)
class ComPathCatalogEntry:
    name: str
    process_names: tuple[str, ...]
    prog_ids: tuple[str, ...]
    path_expressions: tuple[str, ...]


def _versioned_prog_ids(base: str, start: int, end: int) -> tuple[str, ...]:
    return tuple(
        [base, *[f"{base}.{version}" for version in range(end, start - 1, -1)]]
    )


_BUILTIN_COM_PATH_CATALOG: tuple[ComPathCatalogEntry, ...] = (
    ComPathCatalogEntry(
        "Microsoft Word",
        ("winword.exe", "winword"),
        ("Word.Application",),
        ("ActiveDocument.FullName",),
    ),
    ComPathCatalogEntry(
        "Microsoft Excel",
        ("excel.exe", "excel"),
        ("Excel.Application",),
        ("ActiveWorkbook.FullName",),
    ),
    ComPathCatalogEntry(
        "Microsoft PowerPoint",
        ("powerpnt.exe", "powerpnt"),
        ("PowerPoint.Application",),
        ("ActivePresentation.FullName",),
    ),
    ComPathCatalogEntry(
        "Microsoft Visio",
        ("visio.exe", "visio"),
        ("Visio.Application",),
        ("ActiveDocument.FullName",),
    ),
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


class WindowsPathResolver:
    """Resolve the active local path with bounded blocking capacity and cache."""

    def __init__(self, *, capacity: int = _RESOLVER_CAPACITY) -> None:
        self._slots = threading.BoundedSemaphore(max(1, int(capacity)))
        self._state_lock = threading.Lock()
        self._path_cache: dict[
            tuple[int | None, int | None, str, str],
            tuple[float, str | None],
        ] = {}
        self._com_failure_times: dict[str, float] = {}
        self._open_files_failure_times: dict[int, float] = {}
        self._catalog = (
            *_BUILTIN_COM_PATH_CATALOG,
            *_load_user_com_catalog_entries(),
        )

    def privacy_path_required(self, process_name: str, title: str) -> bool:
        if not extract_file_name_from_title(title):
            return False
        process_key = str(process_name or "").strip().casefold()
        if process_key in _EXTRA_LOCAL_FILE_PROCESSES:
            return True
        return any(
            _process_matches_entry(process_name, entry)
            for entry in self._catalog
        )

    def resolve(
        self,
        cache_key: tuple[int | None, int | None, str, str],
        process_name: str,
        title: str,
        pid: int | None,
    ) -> str | None:
        title_path = resolve_title_file_path(title)
        if title_path:
            return title_path
        cached, found = self._cached(cache_key)
        if found:
            return cached
        try:
            resolved = self.resolve_active_file_path(process_name, title, pid)
        except Exception:
            logging.debug(
                "synchronous active path resolution failed",
                exc_info=True,
            )
            resolved = None
        self._store(cache_key, resolved)
        return resolved

    def reset(self) -> None:
        with self._state_lock:
            self._path_cache.clear()
            self._com_failure_times.clear()
            self._open_files_failure_times.clear()

    def resolve_active_file_path(
        self,
        process_name: str,
        window_title: str,
        pid: int | None = None,
    ) -> str | None:
        title_path = resolve_title_file_path(window_title)
        if title_path:
            return title_path

        for prog_id, expression in self._com_candidates(process_name):
            if not self._available(self._com_failure_times, prog_id):
                continue
            try:
                path = self._run_with_timeout(
                    _get_com_file_path_threadsafe,
                    _COM_CALL_TIMEOUT_SECONDS,
                    prog_id,
                    expression,
                )
                if _is_valid_com_path(path, window_title):
                    return split_file_path(path)[0]
            except TimeoutError:
                self._mark_failed(self._com_failure_times, prog_id)
                logging.debug(
                    "active file path com lookup timed out for %s",
                    prog_id,
                )
            except Exception:
                logging.debug(
                    "active file path com lookup failed",
                    exc_info=True,
                )

        fallback = self._resolve_open_file_path(pid, window_title)
        if fallback:
            return fallback
        return _resolve_indexed_file_path(window_title)

    def _run_with_timeout(self, func, timeout_seconds: float, *args):
        if not self._slots.acquire(blocking=False):
            raise TimeoutError("blocking resolver capacity exhausted")
        result_box: list = [None]
        exc_box: list = [None]
        done = threading.Event()

        def worker() -> None:
            try:
                result_box[0] = func(*args)
            except Exception as exc:  # pragma: no cover - forwarded below
                exc_box[0] = exc
            finally:
                done.set()
                self._slots.release()

        threading.Thread(
            target=worker,
            name="WorkTraceBoundedPathCall",
            daemon=True,
        ).start()
        if not done.wait(timeout_seconds):
            raise TimeoutError(
                f"call timed out after {timeout_seconds:.1f}s"
            )
        if exc_box[0] is not None:
            raise exc_box[0]
        return result_box[0]

    def _com_candidates(self, process_name: str) -> list[tuple[str, str]]:
        return [
            (prog_id, expression)
            for entry in self._catalog
            if _process_matches_entry(process_name, entry)
            for prog_id in entry.prog_ids
            if _is_registered_prog_id(prog_id)
            for expression in entry.path_expressions
        ]

    def _resolve_open_file_path(
        self,
        pid: int | None,
        window_title: str | None,
    ) -> str | None:
        if pid is None:
            return None
        title_file = (
            extract_file_name_from_title(window_title)
            or extract_anchor_file_name(window_title)
        )
        if not title_file or not self._available(
            self._open_files_failure_times,
            pid,
        ):
            return None
        try:
            paths = _get_process_open_file_paths(pid)
        except TimeoutError:
            self._mark_failed(self._open_files_failure_times, pid)
            logging.debug("active file path open-files lookup timed out")
            return None
        except Exception:
            logging.debug(
                "active file path open-files lookup failed",
                exc_info=True,
            )
            return None
        return _match_open_file_path(title_file, paths)

    def _available(self, failures: dict, key) -> bool:
        with self._state_lock:
            last_fail = failures.get(key)
        return (
            last_fail is None
            or time.monotonic() - last_fail > _FAILURE_COOLDOWN_SECONDS
        )

    def _mark_failed(self, failures: dict, key) -> None:
        with self._state_lock:
            failures[key] = time.monotonic()

    def _cached(
        self,
        key: tuple[int | None, int | None, str, str],
    ) -> tuple[str | None, bool]:
        now = time.monotonic()
        with self._state_lock:
            entry = self._path_cache.get(key)
            if entry is None:
                return None, False
            expires_at, value = entry
            if expires_at <= now:
                self._path_cache.pop(key, None)
                return None, False
            return value, True

    def _store(
        self,
        key: tuple[int | None, int | None, str, str],
        value: str | None,
    ) -> None:
        ttl = (
            _PATH_SUCCESS_TTL_SECONDS
            if value
            else _PATH_FAILURE_TTL_SECONDS
        )
        with self._state_lock:
            if len(self._path_cache) >= _MAX_PATH_CACHE:
                self._path_cache.clear()
            self._path_cache[key] = (time.monotonic() + ttl, value)


def resolve_title_file_path(window_title: str) -> str | None:
    try:
        title_path = extract_file_path_from_title(window_title)
        if title_path and looks_like_local_file_path(title_path):
            return split_file_path(title_path)[0]
    except Exception:
        logging.debug("active file path title parse failed", exc_info=True)
    return None


def _ensure_com_initialized() -> bool:
    try:
        import pythoncom

        pythoncom.CoInitialize()
        return True
    except Exception:
        logging.debug("COM CoInitialize failed", exc_info=True)
        return False


def _uninitialize_com() -> None:
    try:
        import pythoncom

        pythoncom.CoUninitialize()
    except Exception:
        logging.debug("COM CoUninitialize failed", exc_info=True)


def _get_com_file_path_threadsafe(
    prog_id: str,
    path_expression: str,
) -> str | None:
    _ensure_com_initialized()
    try:
        import win32com.client

        app = win32com.client.GetActiveObject(prog_id)
        value = _evaluate_com_path_expression(app, path_expression)
        return _normalize_com_file_path(value)
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
    if (
        title_path
        and normalize_path_key(title_path) == normalize_path_key(full_path)
    ):
        return True
    title_file = extract_file_name_from_title(window_title)
    return bool(
        title_file and title_file.casefold() == file_name.casefold()
    )


def _resolve_indexed_file_path(window_title: str | None) -> str | None:
    try:
        from ..services.folder_index_query_service import resolve_unique_path_from_title

        return resolve_unique_path_from_title(
            window_title,
            include_excluded=True,
        )
    except Exception:
        logging.debug(
            "active file path folder index lookup failed",
            exc_info=True,
        )
        return None


def _get_process_open_file_paths(pid: int) -> list[str]:
    if sys.platform.startswith("win"):
        return _get_process_open_file_paths_subprocess(pid)
    import psutil

    return [item.path for item in psutil.Process(pid).open_files()]


def _get_process_open_file_paths_subprocess(pid: int) -> list[str]:
    helper_cmd = _open_files_helper_cmd()
    if helper_cmd is None:
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
        raise TimeoutError(
            "open-files helper timed out after "
            f"{_OPEN_FILES_TIMEOUT_SECONDS:.1f}s"
        ) from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"open-files helper failed: {message}")
    raw = json.loads(completed.stdout or "[]")
    if not isinstance(raw, list):
        return []
    return [str(path) for path in raw if str(path or "").strip()]


def _open_files_helper_cmd() -> list[str] | None:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--open-files-helper"]
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
        return ()
    entries: list[ComPathCatalogEntry] = []
    for raw_entry in raw_entries:
        try:
            entries.append(_coerce_com_catalog_entry(raw_entry))
        except ValueError:
            logging.debug(
                "invalid user com path catalog entry skipped",
                exc_info=True,
            )
    return tuple(entries)


def _coerce_com_catalog_entry(raw_entry) -> ComPathCatalogEntry:
    if not isinstance(raw_entry, dict):
        raise ValueError("entry must be an object")
    name = str(raw_entry.get("name") or "User COM entry").strip()
    process_names = _coerce_string_tuple(raw_entry.get("process_names"))
    prog_ids = _coerce_string_tuple(raw_entry.get("prog_ids"))
    path_expressions = _coerce_string_tuple(
        raw_entry.get("path_expressions")
    )
    if not process_names or not prog_ids or not path_expressions:
        raise ValueError(
            "entry requires process_names, prog_ids, and path_expressions"
        )
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
    return tuple(
        str(item).strip()
        for item in items
        if str(item).strip()
    )


def _process_matches_entry(
    process_name: str,
    entry: ComPathCatalogEntry,
) -> bool:
    process_keys = _process_name_keys(process_name)
    return any(
        process_keys & _process_name_keys(alias)
        for alias in entry.process_names
    )


def _process_name_keys(process_name: str) -> set[str]:
    normalized = ntpath.basename(
        str(process_name or "").strip()
    ).casefold()
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


__all__ = [
    "ComPathCatalogEntry",
    "WindowsPathResolver",
    "resolve_title_file_path",
]
