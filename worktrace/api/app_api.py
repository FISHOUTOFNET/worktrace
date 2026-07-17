"""Application-control capabilities for the UI composition root."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..services import privacy_gate_service
from . import settings_api

if TYPE_CHECKING:
    from ..runtime.app_runtime import AppRuntime


def _result_dict(result: Any) -> dict[str, Any]:
    converter = getattr(result, "to_dict", None)
    if converter is not None:
        return dict(converter())
    if isinstance(result, dict):
        return dict(result)
    return {"ok": bool(result)}


def get_collection_status() -> dict[str, Any]:
    """Return the display-safe collection status from one API owner."""

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
        "collector_consecutive_failures": (
            settings_api.get_collector_consecutive_failures()
        ),
        "paused": paused,
        "display": display,
    }


def start_collection_after_privacy_gate(
    runtime: "AppRuntime | None",
) -> dict[str, Any]:
    """Authorize once, then delegate complete startup to the injected runtime."""

    try:
        allowed = privacy_gate_service.is_sensitive_runtime_allowed()
    except Exception:
        logging.exception("privacy notice state read failed")
        allowed = False
    if not allowed:
        return {"ok": False, "error": "请先确认隐私说明"}
    if runtime is None:
        return {"ok": False, "error": "runtime_not_available"}
    try:
        return _result_dict(runtime.start_authorized_collection())
    except Exception:
        logging.exception("application control runtime startup failed")
        return {"ok": False, "error": "collector_start_failed"}


def accept_privacy_notice_and_start(
    runtime: "AppRuntime | None",
) -> dict[str, Any]:
    """Accept installation consent and start the injected runtime."""

    result = settings_api.accept_first_run_notice_for_webview()
    if not result.get("ok"):
        return result
    start_result = start_collection_after_privacy_gate(runtime)
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


def pause_collection_now(runtime: "AppRuntime | None") -> dict[str, Any]:
    """Pause only through the runtime command/acknowledgement channel."""

    if runtime is None:
        return {"ok": False, "error": "runtime_not_available"}
    try:
        result = dict(runtime.pause_collection_now())
    except Exception:
        logging.exception("application control pause failed")
        return {"ok": False, "error": "collector_pause_failed"}
    if not result.get("ok"):
        return result
    return result


def toggle_collection(runtime: "AppRuntime | None") -> dict[str, Any]:
    status = get_collection_status()
    raw_status = str(status.get("status") or "")
    if bool(status.get("paused")) or raw_status != "running":
        result = start_collection_after_privacy_gate(runtime)
        if not result.get("ok"):
            return result
        settings_api.set_user_paused(False)
    else:
        result = pause_collection_now(runtime)
        if not result.get("ok"):
            return result
    return get_collection_status()


def set_clipboard_capture_enabled(
    runtime: "AppRuntime | None",
    enabled: bool,
) -> None:
    if runtime is None:
        raise RuntimeError("runtime_not_available")
    if enabled:
        privacy_gate_service.require_sensitive_runtime_allowed()
    applied = runtime.set_clipboard_capture_enabled(bool(enabled))
    if not applied:
        raise RuntimeError("clipboard_runtime_rejected")


def set_clipboard_capture_policy(
    runtime: "AppRuntime | None",
    enabled: bool,
) -> dict[str, Any]:
    """Apply runtime authorization, persist preference, and compensate failures."""

    if enabled is not True and enabled is not False:
        return {"ok": False, "error": "请选择有效的剪贴板记录状态"}
    previous = bool(settings_api.is_clipboard_capture_enabled())
    try:
        set_clipboard_capture_enabled(runtime, enabled)
    except Exception:
        logging.exception("clipboard authorization or runtime apply failed")
        return {"ok": False, "error": "设置剪贴板记录失败"}

    try:
        result = settings_api.set_clipboard_capture_enabled_for_webview(enabled)
    except Exception:
        logging.exception("clipboard preference persistence failed")
        try:
            set_clipboard_capture_enabled(runtime, previous)
        except Exception:
            logging.exception("clipboard runtime compensation failed")
        return {"ok": False, "error": "设置剪贴板记录失败"}

    if not result.get("ok"):
        try:
            set_clipboard_capture_enabled(runtime, previous)
        except Exception:
            logging.exception("clipboard runtime compensation failed")
        return result
    return {"ok": True, "status": result["status"]}


class ApplicationControl:
    """Explicit runtime-bound application capability object."""

    def __init__(self, runtime: "AppRuntime | None") -> None:
        self._runtime = runtime

    @property
    def runtime(self) -> "AppRuntime | None":
        return self._runtime

    def get_collection_status(self) -> dict[str, Any]:
        return get_collection_status()

    def start_collection_after_privacy_gate(self) -> dict[str, Any]:
        return start_collection_after_privacy_gate(self._runtime)

    def accept_privacy_notice_and_start(self) -> dict[str, Any]:
        return accept_privacy_notice_and_start(self._runtime)

    def pause_collection_now(self) -> dict[str, Any]:
        return pause_collection_now(self._runtime)

    def toggle_collection(self) -> dict[str, Any]:
        return toggle_collection(self._runtime)

    def set_clipboard_capture_policy(self, enabled: bool) -> dict[str, Any]:
        return set_clipboard_capture_policy(self._runtime, enabled)

    def request_shutdown(self) -> None:
        if self._runtime is not None:
            self._runtime.request_shutdown()


__all__ = [
    "ApplicationControl",
    "accept_privacy_notice_and_start",
    "get_collection_status",
    "pause_collection_now",
    "set_clipboard_capture_policy",
    "start_collection_after_privacy_gate",
    "toggle_collection",
]
