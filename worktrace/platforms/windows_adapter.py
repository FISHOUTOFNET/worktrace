"""Canonical Windows platform adapter."""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes

from ..resources.title_parsing import extract_probable_file_name
from ..worker_health import WorkerHealthReporter
from .base import (
    ActiveWindow,
    ClipboardTextEvent,
    PlatformTemporarilyUnavailableError,
)
from .windows_clipboard import ClipboardMonitor
from .windows_path_resolver import WindowsPathResolver, resolve_title_file_path

_HOST_PROCESS_NAMES = frozenset({"applicationframehost.exe"})
_GENERIC_PATH_PROBE_EXCLUDED_PROCESSES = frozenset({
    "chrome.exe", "chrome",
    "msedge.exe", "msedge",
    "firefox.exe", "firefox",
    "brave.exe", "brave",
    "opera.exe", "opera",
    "vivaldi.exe", "vivaldi",
})
_GENERIC_PATH_FAILURE_COOLDOWN_SECONDS = 30.0
_MAX_GENERIC_PATH_FAILURES = 256


class WindowsAdapter:
    """Explicit, resettable owner of Windows collection resources."""

    def __init__(
        self,
        *,
        path_resolver: WindowsPathResolver | None = None,
    ) -> None:
        self._path_resolver = path_resolver or WindowsPathResolver()
        self._clipboard = ClipboardMonitor(self.get_active_window)
        self._generic_path_failures: dict[tuple[int, str, str], float] = {}

    def get_active_window(self) -> ActiveWindow | None:
        import psutil
        import win32gui
        import win32process

        try:
            hwnd = int(win32gui.GetForegroundWindow() or 0)
            if hwnd <= 0:
                return None
            title = win32gui.GetWindowText(hwnd) or ""
            _, raw_pid = win32process.GetWindowThreadProcessId(hwnd)
            pid = int(raw_pid)
            if pid <= 0:
                raise PlatformTemporarilyUnavailableError(
                    "foreground_process_unavailable"
                )
        except PlatformTemporarilyUnavailableError:
            raise
        except Exception as exc:
            raise PlatformTemporarilyUnavailableError(
                "active_window_sampling_failed"
            ) from exc

        process_name = "unknown"
        app_name = "unknown"
        try:
            process = psutil.Process(pid)
            process_name = process.name()
            app_name = process_name
        except ValueError as exc:
            # psutil rejects invalid PIDs with ValueError rather than psutil.Error.
            # A foreground window can disappear between Win32 calls, so this is
            # an observation race, not a Collector invariant failure.
            raise PlatformTemporarilyUnavailableError(
                "foreground_process_unavailable"
            ) from exc
        except psutil.Error:
            pass

        pid, process_name = _resolve_effective_process_identity(
            hwnd,
            pid,
            process_name,
            psutil=psutil,
            win32gui=win32gui,
            win32process=win32process,
        )
        app_name = process_name or app_name

        requires_path = self._path_resolver.privacy_path_required(process_name, title)
        probe_policy = getattr(
            self._path_resolver,
            "should_probe_path",
            self._path_resolver.privacy_path_required,
        )
        policy_probe = bool(probe_policy(process_name, title))
        generic_file_candidate = bool(
            process_name.strip().casefold() not in _GENERIC_PATH_PROBE_EXCLUDED_PROCESSES
            and extract_probable_file_name(title)
        )
        should_probe_path = policy_probe or generic_file_candidate
        file_path_hint = resolve_title_file_path(title)
        if not file_path_hint and should_probe_path:
            generic_probe = generic_file_candidate and not policy_probe
            probe_key = (pid, process_name.casefold(), title)
            if not generic_probe or self._generic_probe_due(probe_key):
                file_path_hint = self._path_resolver.resolve(
                    (hwnd, pid, process_name, title),
                    process_name,
                    title,
                    pid,
                )
                if generic_probe:
                    if file_path_hint:
                        self._generic_path_failures.pop(probe_key, None)
                    else:
                        self._mark_generic_probe_failure(probe_key)

        # ``None`` after an explicit authoritative probe is not proof that the
        # document has no local path. Keep that uncertainty at the platform /
        # privacy boundary so folder-exclusion policy can fail closed without
        # polluting persisted resource facts or report projections.
        path_resolution_uncertain = bool(
            should_probe_path and not file_path_hint and not requires_path
        )

        window_class = None
        try:
            window_class = win32gui.GetClassName(hwnd) or None
        except Exception:
            logging.debug("active window class lookup failed", exc_info=True)
        return ActiveWindow(
            app_name=app_name,
            process_name=process_name,
            window_title=title,
            file_path_hint=file_path_hint,
            pid=pid,
            hwnd=hwnd,
            window_class=window_class,
            privacy_path_required=requires_path,
            path_resolution_uncertain=path_resolution_uncertain,
        )

    def _generic_probe_due(self, key: tuple[int, str, str]) -> bool:
        failed_at = self._generic_path_failures.get(key)
        return (
            failed_at is None
            or time.monotonic() - failed_at >= _GENERIC_PATH_FAILURE_COOLDOWN_SECONDS
        )

    def _mark_generic_probe_failure(self, key: tuple[int, str, str]) -> None:
        if len(self._generic_path_failures) >= _MAX_GENERIC_PATH_FAILURES:
            self._generic_path_failures.clear()
        self._generic_path_failures[key] = time.monotonic()

    def get_idle_seconds(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD),
            ]

        last_input = LASTINPUTINFO()
        last_input.cbSize = ctypes.sizeof(last_input)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input)):
            return 0
        get_tick_count64 = ctypes.windll.kernel32.GetTickCount64
        get_tick_count64.restype = ctypes.c_ulonglong
        current_low = int(get_tick_count64()) & 0xFFFFFFFF
        elapsed_ms = (current_low - int(last_input.dwTime)) & 0xFFFFFFFF
        return max(0, elapsed_ms // 1000)

    def set_clipboard_capture_enabled(self, enabled: bool) -> None:
        self._clipboard.set_enabled(bool(enabled))

    def get_clipboard_events(self) -> list[ClipboardTextEvent]:
        return self._clipboard.drain()

    def run_clipboard_capture(
        self,
        stop_event: threading.Event,
        *,
        health: WorkerHealthReporter,
    ) -> None:
        self._clipboard.run(stop_event, health=health)

    def reset_runtime_state(self) -> None:
        self._clipboard.reset()
        self._generic_path_failures.clear()
        self._path_resolver.reset()

    def shutdown(self) -> None:
        self._clipboard.shutdown()
        self._generic_path_failures.clear()
        self._path_resolver.reset()


def _resolve_effective_process_identity(
    hwnd: int,
    pid: int,
    process_name: str,
    *,
    psutil,
    win32gui,
    win32process,
) -> tuple[int, str]:
    """Resolve a unique app process hosted behind a known Windows frame.

    The physical foreground HWND remains authoritative for title/class sampling.
    We only replace its PID when all non-host descendant windows agree on one
    process. Ambiguous or unavailable enumeration fails closed to the physical
    owner instead of guessing.
    """

    if str(process_name or "").strip().casefold() not in _HOST_PROCESS_NAMES:
        return pid, process_name
    enum_children = getattr(win32gui, "EnumChildWindows", None)
    if not callable(enum_children):
        return pid, process_name

    candidates: dict[int, str] = {}

    def _visit(child_hwnd, _extra):
        try:
            _, child_raw_pid = win32process.GetWindowThreadProcessId(child_hwnd)
            child_pid = int(child_raw_pid)
            if child_pid <= 0 or child_pid == pid:
                return True
            child_name = str(psutil.Process(child_pid).name() or "").strip()
            if not child_name or child_name.casefold() in _HOST_PROCESS_NAMES:
                return True
            candidates[child_pid] = child_name
        except (ValueError, psutil.Error):
            pass
        except Exception:
            logging.debug("host child process lookup failed", exc_info=True)
        return True

    try:
        enum_children(hwnd, _visit, None)
    except Exception:
        logging.debug("host child window enumeration failed", exc_info=True)
        return pid, process_name

    if len(candidates) != 1:
        return pid, process_name
    effective_pid, effective_name = next(iter(candidates.items()))
    return effective_pid, effective_name


__all__ = ["WindowsAdapter"]
