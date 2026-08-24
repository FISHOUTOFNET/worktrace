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

PRIVACY_ACCEPT_FAILED = "privacy_accept_failed"
PRIVACY_GATE_REQUIRED = "privacy_gate_required"
COLLECTOR_START_FAILED = "collector_start_failed"
DATABASE_MAINTENANCE_RECOVERY_REQUIRED = "database_maintenance_recovery_required"

_COLLECTOR_FAILED_MESSAGE = (
    "隐私说明已确认，但记录功能未能启动，请稍后重试或在设置中恢复"
)


class ApplicationRuntimeCapability(Protocol):
    """Narrow runtime capability consumed by API-facing application commands."""

    collector_control: Any
    phase: Any

    def start_authorized_collection(self) -> RuntimeStartResult: ...

    def pause_collection_now(self) -> dict[str, object]: ...

    def is_collection_running_for_maintenance(self) -> bool: ...

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool: ...

    def worker_health_snapshot(self) -> dict[str, object]: ...

    def request_shutdown(self) -> None: ...


class MaintenanceStateCapability(Protocol):
    """Read-only maintenance state required before sensitive runtime resume."""

    @property
    def blocked_reason(self) -> str | None: ...

    def operation_active(self) -> bool: ...

    def recovery_blocked(self) -> bool: ...

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
        background_health_state, degraded_workers = self._background_health_state()
        paused = settings_api.is_user_paused() or raw_status == "paused"
        if paused:
            display = "已暂停"
        elif raw_status == "running":
            if health_state == "failing":
                display = "采集可能中断，请重试"
            elif background_health_state == "degraded":
                display = "记录中，部分后台任务异常"
            elif health_state == "degraded":
                display = "记录中，刚才采集短暂异常"
            elif background_health_state == "starting":
                display = "记录中，后台任务正在准备"
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
            "background_health_state": background_health_state,
            "background_degraded_workers": degraded_workers,
            "paused": paused,
            "display": display,
        }

    def _background_health_state(self) -> tuple[str, list[str]]:
        """Project derived-worker liveness without exposing internal trace data."""

        try:
            snapshot = dict(self.runtime.worker_health_snapshot())
        except Exception:
            logging.exception("background worker health read failed")
            return "unknown", []

        raw_workers = snapshot.get("workers")
        workers = raw_workers if isinstance(raw_workers, dict) else {}
        raw_degraded = snapshot.get("degraded_workers")
        degraded = {
            str(name)
            for name in (raw_degraded if isinstance(raw_degraded, (list, tuple)) else [])
            if str(name or "").strip()
        }

        phase = getattr(self.runtime, "phase", None)
        phase_value = str(getattr(phase, "value", phase) or "").lower()

        # WorkerHealth deliberately tolerates one or two transient failures after
        # a service has been established. AppRuntime phase carries the stronger
        # lifecycle fact: a worker that failed before serving, or whose target is
        # currently in restart backoff, makes the runtime DEGRADED immediately.
        if phase_value == "degraded":
            for name, raw_state in workers.items():
                if not isinstance(raw_state, dict):
                    continue
                if (
                    raw_state.get("running") is False
                    or int(raw_state.get("consecutive_failures") or 0) > 0
                ):
                    degraded.add(str(name))
            return "degraded", sorted(degraded)

        if phase_value in {"failed", "recoverable_failure"}:
            return "degraded", sorted(degraded)
        if phase_value == "starting":
            return "starting", sorted(degraded)
        if degraded:
            return "degraded", sorted(degraded)
        return "healthy", []

    def is_collection_active(self) -> bool:
        """Return whether the collector is actively observing right now.

        This intentionally follows runtime capability rather than persisted
        display status, which can lag a resume heartbeat by a few seconds.
        The privacy gate is not re-read here: collector startup already passes
        that gate, and a later gate loss is converted by the collector loop into
        durable user pause. Avoiding that re-read keeps this one-second desktop
        projection free of installation-metadata disk I/O.
        """

        try:
            if settings_api.is_user_paused():
                return False
            if self.maintenance.operation_active() or self.maintenance.recovery_blocked():
                return False
            if not self.runtime.is_collection_running_for_maintenance():
                return False
            control = getattr(self.runtime, "collector_control", None)
            hold_state = getattr(control, "hold_state", None)
            hold_value = getattr(hold_state, "value", hold_state)
            return str(hold_value or "") == "operational"
        except Exception:
            logging.exception("collection active state read failed")
            return False

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
        accept_result = settings_api.accept_first_run_notice_for_webview()
        if not accept_result.get("ok"):
            return {
                "ok": False,
                "accepted": False,
                "collector_started": False,
                "collector_status": None,
                "error_code": PRIVACY_ACCEPT_FAILED,
                "message": str(accept_result.get("error") or "确认隐私说明失败"),
            }
        start_result = self.start_collection_after_privacy_gate()
        if not start_result.get("ok"):
            # RuntimeStartResult.to_dict() emits ``error_code``; the legacy
            # ``error`` key is only on the maintenance/privacy/exception
            # fallback dicts. Prefer the runtime's authoritative error_code.
            raw_error = str(
                start_result.get("error_code")
                or start_result.get("error")
                or COLLECTOR_START_FAILED
            )
            error_code = _map_collector_start_error_code(raw_error)
            message = str(
                start_result.get("message")
                or _COLLECTOR_FAILED_MESSAGE
            )
            return {
                "ok": False,
                "accepted": True,
                "collector_started": False,
                "collector_status": self._safe_collector_status(),
                "error_code": error_code,
                "message": message,
            }
        return {
            "ok": True,
            "accepted": True,
            "collector_started": True,
            "collector_status": self._slim_collector_status(),
            "error_code": None,
            "message": "已确认隐私说明",
        }

    def _slim_collector_status(self) -> dict[str, Any]:
        full = self.get_collection_status()
        return {
            "status": str(full.get("status") or ""),
            "paused": bool(full.get("paused")),
            "display": str(full.get("display") or ""),
        }

    def _safe_collector_status(self) -> dict[str, Any] | None:
        try:
            return self._slim_collector_status()
        except Exception:
            logging.exception("collector status read after failed start failed")
            return None

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
                # runtime mutation. Gate read exceptions fail closed.
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


def _map_collector_start_error_code(raw_error: str) -> str:
    """Map an internal start error string to a stable public error code."""
    if raw_error == DATABASE_RECOVERY_ERROR:
        return DATABASE_MAINTENANCE_RECOVERY_REQUIRED
    if raw_error == "请先确认隐私说明":
        return PRIVACY_GATE_REQUIRED
    return COLLECTOR_START_FAILED


__all__ = [
    "ApplicationControlService",
    "ApplicationRuntimeCapability",
    "MaintenanceStateCapability",
    "PRIVACY_ACCEPT_FAILED",
    "PRIVACY_GATE_REQUIRED",
    "COLLECTOR_START_FAILED",
    "DATABASE_MAINTENANCE_RECOVERY_REQUIRED",
]
