"""Small process-local health model for AppRuntime-owned derived workers."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone

DEFAULT_CONSECUTIVE_FAILURE_THRESHOLD = 3


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


@dataclass(frozen=True)
class WorkerHealthSnapshot:
    name: str
    started: bool = False
    running: bool = False
    maintenance_paused: bool = False
    last_successful_iteration_at: str = ""
    last_failure_code: str = ""
    consecutive_failures: int = 0

    def degraded(
        self,
        threshold: int = DEFAULT_CONSECUTIVE_FAILURE_THRESHOLD,
    ) -> bool:
        return bool(
            self.started
            and (
                not self.running
                or self.consecutive_failures >= max(1, int(threshold))
            )
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "running": self.running,
            "maintenance_paused": self.maintenance_paused,
            "last_successful_iteration_at": self.last_successful_iteration_at,
            "last_failure_code": self.last_failure_code,
            "consecutive_failures": self.consecutive_failures,
        }


class WorkerHealthRegistry:
    """Thread-safe health state owned by one ``AppRuntime`` instance."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, WorkerHealthSnapshot] = {}

    def reporter(self, name: str) -> "WorkerHealthReporter":
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("worker_name_required")
        with self._lock:
            self._states.setdefault(normalized, WorkerHealthSnapshot(normalized))
        return WorkerHealthReporter(self, normalized)

    def _change(self, name: str, **changes: object) -> None:
        with self._lock:
            current = self._states.setdefault(name, WorkerHealthSnapshot(name))
            self._states[name] = replace(current, **changes)

    def mark_started(self, name: str) -> None:
        self._change(
            name,
            started=True,
            running=True,
            maintenance_paused=False,
        )

    def mark_success(self, name: str) -> None:
        self._change(
            name,
            running=True,
            last_successful_iteration_at=_timestamp(),
            last_failure_code="",
            consecutive_failures=0,
        )

    def mark_failure(self, name: str, code: str) -> None:
        normalized = str(code or "worker_iteration_failed").strip()
        with self._lock:
            current = self._states.setdefault(name, WorkerHealthSnapshot(name))
            self._states[name] = replace(
                current,
                started=True,
                running=True,
                last_failure_code=normalized,
                consecutive_failures=current.consecutive_failures + 1,
            )

    def mark_maintenance_paused(self, name: str, paused: bool) -> None:
        self._change(name, maintenance_paused=bool(paused))

    def mark_stopped(self, name: str) -> None:
        self._change(
            name,
            running=False,
            maintenance_paused=False,
        )

    def snapshots(self) -> dict[str, WorkerHealthSnapshot]:
        with self._lock:
            return dict(self._states)

    def public_snapshot(self) -> dict[str, dict[str, object]]:
        return {
            name: state.to_public_dict()
            for name, state in sorted(self.snapshots().items())
        }

    def degraded_workers(
        self,
        threshold: int = DEFAULT_CONSECUTIVE_FAILURE_THRESHOLD,
    ) -> tuple[str, ...]:
        return tuple(
            name
            for name, state in sorted(self.snapshots().items())
            if state.degraded(threshold)
        )


class WorkerHealthReporter:
    """Narrow capability passed to one blocking worker entrypoint."""

    def __init__(self, registry: WorkerHealthRegistry, name: str) -> None:
        self._registry = registry
        self.name = name

    def started(self) -> None:
        self._registry.mark_started(self.name)

    def succeeded(self) -> None:
        self._registry.mark_success(self.name)

    def failed(self, code: str) -> None:
        self._registry.mark_failure(self.name, code)

    def maintenance_paused(self, paused: bool) -> None:
        self._registry.mark_maintenance_paused(self.name, paused)

    def stopped(self) -> None:
        self._registry.mark_stopped(self.name)


__all__ = [
    "DEFAULT_CONSECUTIVE_FAILURE_THRESHOLD",
    "WorkerHealthRegistry",
    "WorkerHealthReporter",
    "WorkerHealthSnapshot",
]
