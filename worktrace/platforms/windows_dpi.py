from __future__ import annotations

import ctypes
import logging
import sys
from typing import Any


_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
_ERROR_ACCESS_DENIED = 5


def _load_user32() -> Any:
    return ctypes.WinDLL("user32", use_last_error=True)


def _last_error() -> int:
    return int(ctypes.get_last_error())


def _target_context() -> ctypes.c_void_p:
    return ctypes.c_void_p(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)


def _thread_uses_per_monitor_v2(user32: Any) -> bool:
    getter = user32.GetThreadDpiAwarenessContext
    getter.argtypes = []
    getter.restype = ctypes.c_void_p
    comparer = user32.AreDpiAwarenessContextsEqual
    comparer.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    comparer.restype = ctypes.c_bool
    current = getter()
    return bool(current and comparer(current, _target_context()))


def configure_process_dpi_awareness() -> bool:
    """Establish PerMonitorV2 before pywebview creates any Windows UI."""

    if sys.platform != "win32":
        return True

    try:
        user32 = _load_user32()
        if _thread_uses_per_monitor_v2(user32):
            logging.info("dpi awareness already configured context=per_monitor_v2")
            return True

        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_bool
        if setter(_target_context()):
            logging.info("dpi awareness configured context=per_monitor_v2")
            return True

        error = _last_error()
        if error == _ERROR_ACCESS_DENIED and _thread_uses_per_monitor_v2(user32):
            logging.info("dpi awareness provided by process manifest context=per_monitor_v2")
            return True
        logging.warning("dpi awareness configuration failed error=%s", error)
        return False
    except (AttributeError, OSError):
        logging.warning("PerMonitorV2 DPI awareness API unavailable", exc_info=True)
        return False
    except Exception:
        logging.warning("PerMonitorV2 DPI awareness configuration failed", exc_info=True)
        return False
