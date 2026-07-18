"""Explicit process-level maintenance command port.

The coordinator is composed by :class:`AppRuntime` and passed to destructive or
snapshot maintenance callers. Services never register module-global callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class RuntimeMaintenancePort(Protocol):
    def quiesce_for_maintenance(
        self,
        *,
        timeout_seconds: float = 5.0,
        reason: str = "maintenance",
    ) -> dict[str, object]: ...

    def reset_after_database_replacement(
        self,
        *,
        timeout_seconds: float = 5.0,
        reason: str = "database_replacement",
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class MaintenanceResult:
    ok: bool
    collector_active: bool
    command_state_unknown: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "collector_active": self.collector_active,
            "command_state_unknown": self.command_state_unknown,
        }
        if self.error:
            result["error"] = self.error
        return result


class RuntimeMaintenanceCoordinator:
    """Own Collector quiesce/reset commands without changing user intent."""

    def __init__(
        self,
        *,
        collector_active: Callable[[], bool],
        request_quiesce: Callable[[float], dict[str, object]],
        request_reset: Callable[[float], dict[str, object]],
        reset_adapter: Callable[[], None],
        fail_closed: Callable[[str], None],
    ) -> None:
        self._collector_active = collector_active
        self._request_quiesce = request_quiesce
        self._request_reset = request_reset
        self._reset_adapter = reset_adapter
        self._fail_closed = fail_closed

    def quiesce_for_maintenance(
        self,
        *,
        timeout_seconds: float = 5.0,
        reason: str = "maintenance",
    ) -> dict[str, object]:
        if not self._collector_active():
            return MaintenanceResult(True, False).to_dict()
        result = dict(self._request_quiesce(float(timeout_seconds)))
        return self._normalize_result(result, reason=f"{reason}_quiesce")

    def reset_after_database_replacement(
        self,
        *,
        timeout_seconds: float = 5.0,
        reason: str = "database_replacement",
    ) -> dict[str, object]:
        if not self._collector_active():
            self._reset_adapter()
            return MaintenanceResult(True, False).to_dict()
        result = dict(self._request_reset(float(timeout_seconds)))
        normalized = self._normalize_result(result, reason=f"{reason}_reset")
        if bool(normalized.get("ok")):
            self._reset_adapter()
        return normalized

    def _normalize_result(
        self,
        result: dict[str, object],
        *,
        reason: str,
    ) -> dict[str, object]:
        if bool(result.get("ok")):
            result.setdefault("collector_active", True)
            result.setdefault("command_state_unknown", False)
            return result
        if bool(result.get("command_state_unknown")):
            self._fail_closed(reason)
        result.setdefault("collector_active", True)
        return result


__all__ = [
    "MaintenanceResult",
    "RuntimeMaintenanceCoordinator",
    "RuntimeMaintenancePort",
]
