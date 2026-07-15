"""Aggregate application-control facade for the UI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..services import assignment_command_service, privacy_gate_service
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


def start_collection_after_privacy_gate() -> dict[str, Any]:
    """Authorize once, then delegate lifecycle work to ``AppRuntime``."""
    if not privacy_gate_service.is_sensitive_runtime_allowed():
        return {"ok": False, "error": "请先确认隐私说明"}
    if _runtime is None:
        return {"ok": False, "error": "collector_start_failed"}

    background_error = False
    try:
        assignment_command_service.retry_pending_inference(100)
    except Exception:
        background_error = True
        logging.exception("pending assignment inference retry failed")
    try:
        _runtime.start_background_workers()
    except Exception:
        background_error = True
        logging.exception(
            "app_api.start_collection_after_privacy_gate: background workers failed"
        )
    try:
        collector_result = _runtime.start_collector()
    except Exception:
        logging.exception(
            "app_api.start_collection_after_privacy_gate: collector start failed"
        )
        return {"ok": False, "error": "collector_start_failed"}
    if isinstance(collector_result, dict) and not collector_result.get("ok"):
        return dict(collector_result)
    return {"ok": True, "background_worker_degraded": background_error}


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
    """Authorize enabling before applying the runtime state."""
    if enabled:
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


def start_background_workers() -> bool:
    """Low-level lifecycle facade; authorization is owned by startup commands."""
    if _runtime is not None:
        return _runtime.start_background_workers()
    return False


def request_shutdown() -> None:
    if _runtime is not None:
        _runtime.request_shutdown()


def owns_collector() -> bool:
    return bool(_runtime is not None and _runtime.owns_collector)


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
