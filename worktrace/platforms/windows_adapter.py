from __future__ import annotations

import ctypes
import logging
import ntpath
from ctypes import wintypes

import psutil

from ..path_utils import (
    extract_file_path_from_title,
    looks_like_anchor_file_path,
    normalize_path_key,
    split_file_path,
)
from ..resource_patterns import extract_anchor_file_name
from .base import ActiveWindow


class WindowsAdapter:
    def get_active_window(self) -> ActiveWindow:
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = ""
        app_name = ""
        try:
            process = psutil.Process(pid)
            process_name = process.name()
            app_name = process_name
        except psutil.Error:
            process_name = "unknown"
            app_name = "unknown"
        file_path_hint = _resolve_active_file_path(process_name, title)
        return ActiveWindow(
            app_name=app_name,
            process_name=process_name,
            window_title=title,
            file_path_hint=file_path_hint,
        )

    def get_idle_seconds(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        last_input = LASTINPUTINFO()
        last_input.cbSize = ctypes.sizeof(last_input)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input)):
            return 0
        tick_count = ctypes.windll.kernel32.GetTickCount()
        return int((tick_count - last_input.dwTime) / 1000)


def _resolve_active_file_path(process_name: str, window_title: str) -> str | None:
    try:
        title_path = extract_file_path_from_title(window_title)
        if title_path and looks_like_anchor_file_path(title_path):
            logging.debug("active file path resolved from window title")
            return title_path
    except Exception:
        logging.debug("active file path title parse failed", exc_info=True)

    process = (process_name or "").casefold()
    if not any(token in process for token in ("winword", "excel", "powerpnt", "wps", "et", "wpp")):
        return None

    for prog_id, attr in _office_candidates(process):
        try:
            path = _get_com_file_path(prog_id, attr)
            if _is_valid_com_path(path, window_title):
                logging.debug("active file path resolved from office com")
                return path
        except Exception:
            logging.debug("active file path com lookup failed", exc_info=True)
    return None


def _office_candidates(process_name: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if "winword" in process_name:
        candidates.append(("Word.Application", "ActiveDocument.FullName"))
    if "excel" in process_name:
        candidates.append(("Excel.Application", "ActiveWorkbook.FullName"))
    if "powerpnt" in process_name:
        candidates.append(("PowerPoint.Application", "ActivePresentation.FullName"))
    if "wps" in process_name:
        candidates.append(("wps.Application", "ActiveDocument.FullName"))
    if "et" in process_name:
        candidates.append(("et.Application", "ActiveWorkbook.FullName"))
    if "wpp" in process_name:
        candidates.append(("wpp.Application", "ActivePresentation.FullName"))
    return candidates


def _get_com_file_path(prog_id: str, attr_path: str) -> str | None:
    import win32com.client

    app = win32com.client.GetActiveObject(prog_id)
    value = app
    for attr in attr_path.split("."):
        value = getattr(value, attr)
    return str(value) if value else None


def _is_valid_com_path(path: str | None, window_title: str | None) -> bool:
    if not path or not looks_like_anchor_file_path(path):
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

    title_file = extract_anchor_file_name(window_title)
    return bool(title_file and title_file.casefold() == file_name.casefold())
