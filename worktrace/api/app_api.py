"""Application-control capability boundary for the UI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..services import activity_lifecycle_service, privacy_gate_service
from . import settings_api

if TYPE_CHECKING:
    from ..runtime.app_runtime import AppRuntime

_runtime: "AppRuntime | None" = None


def set_runtime(runtime: "AppRuntime | None") -> None:
    """Composition-root hook; not part of the WebView capability surface."""

    global _runtime
    _runtime = runtime


def get_runtime() -> "AppRuntime | None":
    """Test/diagnostic hook; intentionally omitted from ``__all__``."""

    return _runtime


def _result_dict(result: Any) -> dict[str, Any]:
    converter = getattr(result, "to_dict", None)
    if converter is not None:
        return dict(converter())
    if isinstance(result, dict):
        return dict(result)
    return {"ok": bool(result)}


def get_collection_status() -> dict[str, Any]:
    """Return the privacy-safe collection status from one API owner."""

    raw_status = settings_api.get_collector_status()
    health_state = settings_api.get_collector_health_state()
    paused = settings_api.is_user_paused() or raw_status == "paused"
    if paused:
        display = "已暂停"
    elif raw_status == "running":
        if health_state == "degraded":
            display = "记录中，刚才采集短暂异常"
        elif health_state == "failing":
            display = "采集可能中断，请重试"
        else:
            display = "记录中"
    elif raw_status == "error":
        display = "状态异常"
    else:
        display = "采集器未运行"
    return {
        "ok": True,
        "status": raw_status,
        "collector_health_state": health_state,
        "collector_last_successful_observation_at": (
            settings_api.get_collector_last_successful_observation_at()
        ),
        "collector_last_failure_code": (
            settings_api.get_collector_last_failure_code()
        ),
        "collector_consecutive_failures": (
            settings_api.get_collector_consecutive_failures()
        ),
        "paused": paused,
        "display": display,
    }


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


def accept_privacy_notice_and_start() -> dict[str, Any]:
    """Accept installation consent and start the authorized runtime atomically."""

    result = settings_api.accept_first_run_notice_for_webview()
    if not result.get("ok"):
        return result
    start_result = start_collection_after_privacy_gate()
    if not start_result.get("ok"):
        return {
            "ok": False,
            "accepted": True,
            "error": "隐私说明已确认，但记录功能未能启动，请点击恢复记录重试",
        }
    payload: dict[str, Any] = {
        "ok": True,
        "accepted": True,
        "message": "已确认隐私说明",
        "background_worker_degraded": bool(
            start_result.get("background_worker_degraded")
        ),
    }
    try:
        payload["status"] = get_collection_status()
    except Exception:
        logging.exception("collection status refresh after privacy acceptance failed")
    return payload


def pause_collection_now() -> dict[str, Any]:
    try:
        if _runtime is not None:
            result = dict(_runtime.pause_collection_now())
            if not bool(result.get("collector_active", True)):
                activity_lifecycle_service.pause_collection(reason="pause_fallback")
            return result
        activity_lifecycle_service.pause_collection(reason="pause_fallback")
        return {"ok": False, "pause_pending": True}
    except Exception:
        logging.exception("app_api.pause_collection_now failed")
        try:
            activity_lifecycle_service.pause_collection(reason="pause_fallback")
        except Exception:
            logging.exception("app_api.pause_collection_now fallback failed")
        return {"ok": False, "pause_pending": True}


def toggle_collection() -> dict[str, Any]:
    """Toggle start/pause without duplicating lifecycle rules in the bridge."""

    status = get_collection_status()
    raw_status = str(status.get("status") or "")
    if bool(status.get("paused")) or raw_status != "running":
        result = start_collection_after_privacy_gate()
        if not result.get("ok"):
            return result
        settings_api.set_user_paused(False)
    else:
        result = pause_collection_now()
        if not result.get("ok"):
            return result
    return get_collection_status()


def set_clipboard_capture_enabled(enabled: bool) -> None:
    """Authorize and apply a live clipboard runtime state when one exists."""

    if enabled and _runtime is not None:
        privacy_gate_service.require_sensitive_runtime_allowed()
    if _runtime is not None:
        applied = _runtime.set_clipboard_capture_enabled(bool(enabled))
        if not applied:
            raise RuntimeError("clipboard_runtime_rejected")


def set_clipboard_capture_policy(enabled: bool) -> dict[str, Any]:
    """Apply runtime authorization, persist preference, and compensate failures."""

    if enabled is not True and enabled is not False:
        return {"ok": False, "error": "请选择有效的剪贴板记录状态"}
    previous = bool(settings_api.is_clipboard_capture_enabled())
    try:
        set_clipboard_capture_enabled(enabled)
    except Exception:
        logging.exception("clipboard authorization or runtime apply failed")
        return {"ok": False, "error": "设置剪贴板记录失败"}

    try:
        result = settings_api.set_clipboard_capture_enabled_for_webview(enabled)
    except Exception:
        logging.exception("clipboard preference persistence failed")
        try:
            set_clipboard_capture_enabled(previous)
        except Exception:
            logging.exception("clipboard runtime compensation failed")
        return {"ok": False, "error": "设置剪贴板记录失败"}

    if not result.get("ok"):
        try:
            set_clipboard_capture_enabled(previous)
        except Exception:
            logging.exception("clipboard runtime compensation failed")
        return result
    return {"ok": True, "status": result["status"]}


def start_collector() -> dict[str, object]:
    """Internal diagnostic hook; omitted from the WebView capability surface."""

    if _runtime is not None:
        return dict(_runtime.start_collector())
    return {"ok": False, "error": "collector_start_failed"}


def start_background_workers() -> dict[str, object]:
    """Internal diagnostic hook; omitted from the WebView capability surface."""

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


__all__ = [
    "accept_privacy_notice_and_start",
    "get_collection_status",
    "pause_collection_now",
    "request_shutdown",
    "set_clipboard_capture_policy",
    "start_collection_after_privacy_gate",
    "toggle_collection",
]
