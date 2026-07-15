"""Aggregate application-control facade for the UI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..services.privacy_gate_service import is_sensitive_runtime_allowed
from ..services.runtime_activity_state_service import record_runtime_boundary
from . import settings_api

if TYPE_CHECKING:
    from ..runtime.app_runtime import AppRuntime

_runtime: "AppRuntime | None" = None


def set_runtime(runtime: "AppRuntime | None") -> None:
    """Register the active ``AppRuntime`` instance."""
    global _runtime
    _runtime = runtime


def get_runtime() -> "AppRuntime | None":
    return _runtime


def start_collection_after_privacy_gate() -> dict[str, Any]:
    """Start workers and collector only after the privacy gate is accepted."""
    try:
        notice_accepted = is_sensitive_runtime_allowed()
    except Exception:
        logging.exception(
            "app_api.start_collection_after_privacy_gate: privacy gate read "
            "failed; failing closed"
        )
        return {"ok": False, "error": "请先确认隐私说明"}
    if not notice_accepted:
        return {"ok": False, "error": "请先确认隐私说明"}
    if _runtime is None:
        return {"ok": False, "error": "collector_start_failed"}

    background_error = False
    try:
        _runtime.start_background_workers()
    except Exception:
        background_error = True
        logging.exception(
            "app_api.start_collection_after_privacy_gate: background "
            "workers start failed after gate passed"
        )
    try:
        collector_result = _runtime.start_collector()
    except Exception:
        logging.exception(
            "app_api.start_collection_after_privacy_gate: collector "
            "start failed after gate passed"
        )
        return {"ok": False, "error": "collector_start_failed"}
    if isinstance(collector_result, dict) and not collector_result.get("ok"):
        return dict(collector_result)
    return {
        "ok": True,
        "background_worker_degraded": background_error,
    }


def pause_collection_now() -> dict[str, Any]:
    """Pause through the runtime lifecycle owner."""
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
    """Apply a clipboard privacy toggle immediately to the live adapter."""
    if enabled and not is_sensitive_runtime_allowed():
        raise PermissionError("privacy_notice_required")
    if _runtime is not None:
        _runtime.set_clipboard_capture_enabled(bool(enabled))


def start_collector() -> dict[str, object]:
    if _runtime is not None:
        return dict(_runtime.start_collector())
    return {"ok": False, "error": "collector_start_failed"}


def start_background_workers() -> bool:
    if _runtime is not None:
        return _runtime.start_background_workers()
    return False


def request_shutdown() -> None:
    if _runtime is not None:
        _runtime.request_shutdown()


def owns_collector() -> bool:
    if _runtime is not None:
        return _runtime.owns_collector
    return False


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
