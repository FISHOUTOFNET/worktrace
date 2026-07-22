"""Application-control service with explicitly injected runtime capabilities."""
from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from typing import Any, Protocol

from ..runtime.contracts import RuntimeStartResult
from ..services import privacy_gate_service
from ..services.database_maintenance_service import MaintenanceInProgressError
from ..write_gate import DATABASE_RECOVERY_ERROR
from . import settings_api


class ApplicationRuntimeCapability(Protocol):
    """Narrow runtime capability consumed by API-facing application commands."""

    def start_authorized_collection(self) -> RuntimeStartResult: ...

    def pause_collection_now(self) -> dict[str, object]: ...

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool: ...

    def request_shutdown(self) -> None: ...


class MaintenanceStateCapability(Protocol):
    """Read-only maintenance state required before sensitive runtime resume."""

    @property
    def blocked_reason(self) -> str | None: ...

    def external_runtime_mutation_guard(self) -> AbstractContextManager[None]: ...


class ApplicationControlService:
    """Bridge-facing application commands bound to explicit process capabilities."""

    def __init__(
        self,
        runtime: ApplicationRuntimeCapability,
        maintenance: MaintenanceStateCapability,
    ) -> None:
        if runtime is None:
            raise ValueError("application_runtime_required")
        if maintenance is None:
            raise ValueError("maintenance_capability_required")
        self.runtime = runtime
        self.maintenance = maintenance

    def get_collection_status(self) -> dict[str, Any]:
        raw_status = settings_api.get_collector_status()
        health_state = settings_api.get_collector_health_state()
        paused = settings_api.is_user_paused() or raw_status == "paused"
        if paused:
            display = "已暂停"
        elif raw_status == "running":
            display = {
                "degraded": "记录中，刚才采集短暂异常",
                "failing": "采集可能中断，请重试",
            }.get(health_state, "记录中")
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

    def start_collection_after_privacy_gate(self) -> dict[str, Any]:
        try:
            with self.maintenance.external_runtime_mutation_guard():
                # Privacy authorization must be verified inside the guard so
                # that maintenance state cannot change between the check and
                # the runtime mutation. Gate read exceptions fail closed.
                if not privacy_gate_service.is_sensitive_runtime_allowed():
                    return {"ok": False, "error": "请先确认隐私说明"}
                result = self.runtime.start_authorized_collection()
                if not isinstance(result, RuntimeStartResult):
                    raise TypeError("runtime_start_result_required")
                return result.to_dict()
        except MaintenanceInProgressError:
            return {
                "ok": False,
                "error": DATABASE_RECOVERY_ERROR,
                "message": "维护状态尚未恢复，暂不能开始记录",
            }
        except Exception:
            logging.exception("runtime authorized startup failed")
            return {"ok": False, "error": "collector_start_failed"}

    def accept_privacy_notice_and_start(self) -> dict[str, Any]:
        result = settings_api.accept_first_run_notice_for_webview()
        if not result.get("ok"):
            return result
        start_result = self.start_collection_after_privacy_gate()
        if not start_result.get("ok"):
            return {
                "ok": False,
                "accepted": True,
                "error": str(start_result.get("error") or "collector_start_failed"),
                "message": str(
                    start_result.get("message")
                    or "隐私说明已确认，但记录功能未能启动，请点击恢复记录重试"
                ),
            }
        payload: dict[str, Any] = {
            "ok": True,
            "accepted": True,
            "message": "已确认隐私说明",
            "degraded": bool(start_result.get("degraded")),
        }
        payload["status"] = self.get_collection_status()
        return payload

    def pause_collection_now(self) -> dict[str, Any]:
        try:
            return dict(self.runtime.pause_collection_now())
        except Exception:
            logging.exception("pause collection command failed")
            return {
                "ok": False,
                "pause_pending": False,
                "error": "collector_pause_failed",
            }

    def toggle_collection(self) -> dict[str, Any]:
        status = self.get_collection_status()
        raw_status = str(status.get("status") or "")
        if bool(status.get("paused")) or raw_status != "running":
            result = self.start_collection_after_privacy_gate()
            if not result.get("ok"):
                return result
            settings_api.set_user_paused(False)
        else:
            result = self.pause_collection_now()
            if not result.get("ok"):
                return result
        return self.get_collection_status()

    def set_clipboard_capture_enabled(self, enabled: bool) -> None:
        if enabled:
            with self.maintenance.external_runtime_mutation_guard():
                # Privacy authorization must be verified inside the guard so
                # that maintenance state cannot change between the check and
                # the runtime mutation. Gate read exceptions fail closed.
                privacy_gate_service.require_sensitive_runtime_allowed()
                applied = self.runtime.set_clipboard_capture_enabled(True)
        else:
            # Disabling clipboard capture is always allowed, including during
            # active maintenance, so that sensitive observation can be stopped
            # without waiting for the operation lock.
            applied = self.runtime.set_clipboard_capture_enabled(False)
        if not applied:
            raise RuntimeError("clipboard_runtime_rejected")

    def set_clipboard_capture_policy(self, enabled: bool) -> dict[str, Any]:
        if enabled is not True and enabled is not False:
            return {"ok": False, "error": "请选择有效的剪贴板记录状态"}
        previous = bool(settings_api.is_clipboard_capture_enabled())
        try:
            self.set_clipboard_capture_enabled(enabled)
        except Exception:
            logging.exception("clipboard authorization or runtime apply failed")
            return {"ok": False, "error": "设置剪贴板记录失败"}
        try:
            result = settings_api.set_clipboard_capture_enabled_for_webview(enabled)
        except Exception:
            logging.exception("clipboard preference persistence failed")
            self._compensate_clipboard(previous)
            return {"ok": False, "error": "设置剪贴板记录失败"}
        if not result.get("ok"):
            self._compensate_clipboard(previous)
            return result
        return {"ok": True, "status": result["status"]}

    def _compensate_clipboard(self, previous: bool) -> None:
        try:
            self.set_clipboard_capture_enabled(previous)
        except Exception:
            logging.exception("clipboard runtime compensation failed")

    def request_shutdown(self) -> None:
        self.runtime.request_shutdown()


__all__ = [
    "ApplicationControlService",
    "ApplicationRuntimeCapability",
    "MaintenanceStateCapability",
]
