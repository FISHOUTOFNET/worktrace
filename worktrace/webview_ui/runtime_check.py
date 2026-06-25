"""WebView2 Runtime availability check (Windows).

Phase 1. Detects whether the Microsoft Edge WebView2 Runtime is likely
installed by reading the EdgeUpdate registry keys. Never downloads anything.

On non-Windows platforms, returns ``"unknown"`` so tests are not blocked.

The check is intentionally best-effort: if anything goes wrong reading the
registry, it returns ``"unknown"`` rather than raising, so a failed detection
does not block startup. The caller still surfaces a clear error message when
the runtime is genuinely missing.

As of Phase 1, the WebView2 Runtime is a blocking runtime prerequisite for
WorkTrace. When it is missing on Windows, the user is prompted to install it
and WorkTrace exits with a non-zero code.
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

logger = logging.getLogger(__name__)

RuntimeStatus = Literal["installed", "missing", "unknown"]

# EdgeUpdate client GUID for the WebView2 Runtime.
_WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

_MISSING_HINT = (
    "WorkTrace 需要 Microsoft Edge WebView2 Runtime 才能启动，但未检测到该运行时。"
    "请从 Microsoft 官方渠道下载并安装 Microsoft Edge WebView2 Runtime，"
    "然后重新启动 WorkTrace。"
)


def detect_webview2_runtime() -> RuntimeStatus:
    """Return the WebView2 Runtime availability status.

    Returns one of:
    - ``"installed"``: the runtime's registry key and version were found.
    - ``"missing"``: the registry key is absent on Windows.
    - ``"unknown"``: non-Windows platform, or detection raised an exception.

    This function never raises.
    """
    if sys.platform != "win32":
        return "unknown"
    try:
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for path in (
                rf"Software\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_GUID}",
                rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_GUID}",
            ):
                try:
                    with winreg.OpenKey(hive, path) as key:
                        version, _ = winreg.QueryValueEx(key, "pv")
                        if version and version != "0.0.0.0":
                            return "installed"
                except OSError:
                    continue
        return "missing"
    except Exception:
        logger.exception("webview2 runtime detection failed")
        return "unknown"


def is_webview2_available() -> bool:
    """Convenience boolean: True if the runtime is installed or unknown.

    ``unknown`` is treated as available so non-Windows and detection failures
    do not block startup; the actual failure (if any) is surfaced by pywebview
    when the window is created. On Windows, a definitive ``missing`` result is
    treated as unavailable so the caller can exit with a clear message instead
    of attempting to start the WebView backend.
    """
    return detect_webview2_runtime() != "missing"


def missing_runtime_message() -> str:
    """Return the user-facing message shown when the runtime is missing."""
    return _MISSING_HINT
