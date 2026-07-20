"""Neutral data contracts for the WorkTrace runtime startup handshake."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkerStartupState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class WorkerStartupStatus:
    state: WorkerStartupState
    ready: bool
    started: bool = False
    error_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "ready": self.ready,
            "started": self.started,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class RuntimeStartResult:
    """Complete and exact result of the authorized startup sequence."""

    ok: bool
    collector_ready: bool
    workers: dict[str, WorkerStartupStatus]
    already_running: bool = False
    degraded: bool = False
    error_code: str | None = None

    @property
    def failed_workers(self) -> tuple[str, ...]:
        return tuple(name for name, status in self.workers.items() if not status.ready)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "collector_ready": self.collector_ready,
            "workers": {
                name: status.to_dict()
                for name, status in sorted(self.workers.items())
            },
            "already_running": self.already_running,
            "degraded": self.degraded,
            "error_code": self.error_code,
        }


__all__ = [
    "RuntimeStartResult",
    "WorkerStartupState",
    "WorkerStartupStatus",
]
