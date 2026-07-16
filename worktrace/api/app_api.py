"""Aggregate application-control facade for the UI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..services import privacy_gate_service
from ..services.runtime_activity_state_service import record_runtime_boundary
from . import settings_api

if TYPE_CHECKING:
    from ..runtime.app_runtime import AppRuntime

_runtime: "AppRuntime | None" = None


def set_runtime(runtime: "AppRuntime | None") -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> "AppRuntime | None":
    return _runtime


def _result_dict(result: Any) -> dict[str, Any]:
    converter = getattr(result, "to_dict", None)
    if converter is not None:
        return dict(converter())
    if isinstance(result, dict):
        return dict(result)
    return {"ok": bool(result)}


def start_collection_after_privacy_gate() -> dict[str, Any]:
    """Authorize once, then delegate the complete startup to ``AppRuntime``."""

    try:
        allowed = privacy_gate_service.is_sensitive_runtime_allowed()
    except Exception:
        logging.exception("privacy notice state read failed")
        allowed = False
    if not allowed:
        return {"ok": False, "error": "请先确认隐私说明"}
    if _runtime is None:
        return {"ok": False, "error": "collector_start_failed"}

    try:
        return _result_dict(_runtime.start_authorized_collection())
    except Exception:
        logging.exception(
            "app_api.start_collection_after_privacy_gate: runtime startup failed"
        )
        return {"ok": False, "error": "collector_start_failed"}


def pause_collection_now() -> dict[str, Any]:
    try:
        if _runtime is not None:
            return dict(_runtime.pause_collection_now())
        settings_api.set_user_paused(True)
        record_runtime_boundary("pause_fallback")
        return {"ok": False, "pause_pending": True}
    except Exception:
        logging.exception("app_api.pause_collection_now failed")
        try:
            settings_api.set_user_paused(True)
            record_runtime_boundary("pause_fallback")
        except Exception:
            logging.exception("app_api.pause_collection_now fallback failed")
        return {"ok": False, "pause_pending": True}


def set_clipboard_capture_enabled(enabled: bool) -> None:
    """Authorize and apply a live clipboard runtime state when one exists."""

    if enabled and _runtime is not None:
        privacy_gate_service.require_sensitive_runtime_allowed()
    if _runtime is not None:
        applied = _runtime.set_clipboard_capture_enabled(bool(enabled))
        if not applied:
            raise RuntimeError("clipboard_runtime_rejected")


def start_collector() -> dict[str, object]:
    """Low-level lifecycle facade; authorization is owned by startup commands."""

    if _runtime is not None:
        return dict(_runtime.start_collector())
    return {"ok": False, "error": "collector_start_failed"}


def start_background_workers() -> dict[str, object]:
    """Return explicit worker readiness for diagnostics and tests."""

    if _runtime is None:
        return {
            "ready": False,
            "index_ready": False,
            "history_ready": False,
            "index_started": False,
            "history_started": False,
            "error": "runtime_not_registered",
        }
    return _result_dict(_runtime.start_background_workers())


def request_shutdown() -> None:
    if _runtime is not None:
        _runtime.request_shutdown()


def owns_collector() -> bool:
    """Compatibility UI query for the application-instance lease."""

    return bool(
        _runtime is not None
        and getattr(_runtime, "owns_application_instance", False)
    )


__all__ = [
    "get_runtime",
    "owns_collector",
    "pause_collection_now",
    "request_shutdown",
    "set_clipboard_capture_enabled",
    "set_runtime",
    "start_background_workers",
    "start_collection_after_privacy_gate",
    "start_collector",
]
