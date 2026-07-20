"""Single application coordinator for snapshot and replacement maintenance."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Protocol

from ..collector.runtime_control import RuntimeCollectorControl
from ..database_content_manifest import DELETE_ORDER
from ..db import get_connection, seed_defaults
from ..domain_unit_of_work import DomainUnitOfWork
from ..write_gate import DATABASE_WRITE_GATE
from . import privacy_gate_service
from .database_maintenance_barrier import drain_existing_writers
from .database_replacement_generation_service import (
    capture_replacement_generation_floor,
    publish_database_replacement,
)
from .runtime_activity_state_service import clear_runtime_activity_state
from .settings_service import get_bool_setting, get_setting, set_settings


class RuntimeMaintenanceControl(Protocol):
    """Complete runtime capability required by the sole maintenance owner."""

    collector_control: RuntimeCollectorControl

    def is_collection_running_for_maintenance(self) -> bool: ...

    def quiesce_collection_for_maintenance(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]: ...

    def reset_after_database_replacement(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]: ...

    def restore_after_maintenance(
        self,
        state: "RuntimeMaintenanceState",
        *,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]: ...


class MaintenanceInProgressError(RuntimeError):
    """Another maintenance operation already owns the application boundary."""


class CollectorCommandNotAcknowledgedError(RuntimeError):
    """A runtime maintenance command did not reach a known successful state."""

    def __init__(self, message: str, *, fail_closed: bool = False) -> None:
        super().__init__(message)
        self.fail_closed = bool(fail_closed)


class MaintenanceRecoveryError(RuntimeError):
    """Fail-closed maintenance state could not be verified as recovered."""


class MaintenanceIntent(str, Enum):
    CONSISTENT_SNAPSHOT = "consistent_snapshot"
    DATABASE_REPLACEMENT = "database_replacement"


class MaintenancePhase(str, Enum):
    IDLE = "idle"
    HOLD_REQUESTED = "hold_requested"
    HELD = "held"
    DRAINING = "draining"
    EXCLUSIVE = "exclusive"
    RESETTING = "resetting"
    RESTORING = "restoring"
    RELEASING = "releasing"
    FAILED_CLOSED = "failed_closed"


@dataclass(frozen=True)
class RuntimeMaintenanceState:
    """Pre-maintenance state required for deterministic restoration."""

    privacy_notice_accepted: bool
    user_paused: bool
    collector_running: bool
    collector_status: str
    runtime_generation: int
    replacement_epoch: int


@dataclass(frozen=True)
class MaintenanceStatus:
    """Exact backend-owned maintenance status exposed through every API surface."""

    maintenance_in_progress: bool
    maintenance_restored: bool
    recovery_blocked: bool
    blocked_reason: str | None
    collector_running: bool
    collector_status: str
    user_paused: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "maintenance_in_progress": self.maintenance_in_progress,
            "maintenance_restored": self.maintenance_restored,
            "recovery_blocked": self.recovery_blocked,
            "blocked_reason": self.blocked_reason,
            "collector_running": self.collector_running,
            "collector_status": self.collector_status,
            "user_paused": self.user_paused,
        }


class RuntimeMaintenanceCoordinator:
    """Own the only maintenance state machine, lock order and failure recovery."""

    def __init__(self) -> None:
        self._operation_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._phase = MaintenancePhase.IDLE
        self._runtime_control: RuntimeMaintenanceControl | None = None
        self._blocked_reason: str | None = None

    def register_runtime_control(self, control: RuntimeMaintenanceControl) -> None:
        if control is None:
            raise ValueError("runtime_maintenance_control_required")
        with self._state_lock:
            self._runtime_control = control

    def clear_runtime_control(
        self,
        control: RuntimeMaintenanceControl | None = None,
    ) -> None:
        with self._state_lock:
            if control is None or self._runtime_control is control:
                self._runtime_control = None

    @property
    def phase(self) -> MaintenancePhase:
        with self._state_lock:
            return self._phase

    @property
    def blocked_reason(self) -> str | None:
        with self._state_lock:
            return self._blocked_reason

    def active(self) -> bool:
        return (
            self.phase is not MaintenancePhase.IDLE
            or self.blocked_reason is not None
            or DATABASE_WRITE_GATE.active()
        )

    def status(self) -> MaintenanceStatus:
        control = self._control()
        collector_running = bool(
            control is not None
            and control.is_collection_running_for_maintenance()
        )
        phase = self.phase
        blocked_reason = self.blocked_reason
        gate_active = DATABASE_WRITE_GATE.active()
        recovery_blocked = (
            phase is MaintenancePhase.FAILED_CLOSED
            or blocked_reason is not None
        )
        in_progress = (
            phase not in {MaintenancePhase.IDLE, MaintenancePhase.FAILED_CLOSED}
            or gate_active
        )
        return MaintenanceStatus(
            maintenance_in_progress=in_progress,
            maintenance_restored=not in_progress and not recovery_blocked,
            recovery_blocked=recovery_blocked,
            blocked_reason=blocked_reason,
            collector_running=collector_running,
            collector_status=str(
                get_setting("collector_status", "stopped") or "stopped"
            ),
            user_paused=get_bool_setting("user_paused", False),
        )

    def _set_phase(self, phase: MaintenancePhase) -> None:
        with self._state_lock:
            self._phase = phase

    def _control(self) -> RuntimeMaintenanceControl | None:
        with self._state_lock:
            return self._runtime_control

    def _latch_fail_closed(self, reason: str) -> None:
        with self._state_lock:
            self._blocked_reason = str(reason or "maintenance_failed_closed")
            self._phase = MaintenancePhase.FAILED_CLOSED

    def recover_fail_closed(self) -> None:
        """Clear the latch only after the runtime boundary is operational."""

        with self._state_lock:
            if self._blocked_reason is None:
                return
            control = self._runtime_control
        if control is None or DATABASE_WRITE_GATE.active():
            raise MaintenanceRecoveryError("maintenance_recovery_not_verified")
        hold_state = control.collector_control.hold_state.value
        if hold_state != "operational":
            raise MaintenanceRecoveryError("maintenance_recovery_not_verified")
        set_settings(
            {
                "maintenance_fail_closed": "false",
                "maintenance_fail_closed_reason": "",
            }
        )
        with self._state_lock:
            if self._runtime_control is not control:
                raise MaintenanceRecoveryError("maintenance_recovery_superseded")
            self._blocked_reason = None
            self._phase = MaintenancePhase.IDLE

    @staticmethod
    def _replacement_epoch() -> int:
        conn = get_connection()
        try:
            values = capture_replacement_generation_floor(conn)
            return max((int(value) for value in values.values()), default=0)
        finally:
            conn.close()

    def _capture_state(
        self,
        control: RuntimeMaintenanceControl | None,
    ) -> RuntimeMaintenanceState:
        collector_running = bool(
            control is not None
            and control.is_collection_running_for_maintenance()
        )
        return RuntimeMaintenanceState(
            privacy_notice_accepted=bool(
                privacy_gate_service.is_privacy_notice_accepted()
            ),
            user_paused=get_bool_setting("user_paused", False),
            collector_running=collector_running,
            collector_status=str(
                get_setting("collector_status", "stopped") or "stopped"
            ),
            runtime_generation=DATABASE_WRITE_GATE.generation(),
            replacement_epoch=self._replacement_epoch(),
        )

    @staticmethod
    def _query_command(
        control: RuntimeMaintenanceControl,
        command_id: str,
    ) -> dict[str, object] | None:
        if not command_id:
            return None
        value = control.collector_control.query_command(command_id)
        return dict(value) if isinstance(value, dict) else None

    def _require_ack(
        self,
        result: dict[str, object],
        *,
        control: RuntimeMaintenanceControl,
        command_kind: str,
        terminal_state: str,
        reason: str,
    ) -> None:
        resolved = dict(result)
        command_id = str(resolved.get("command_id") or "")
        if bool(resolved.get("command_state_unknown")):
            queried = self._query_command(control, command_id)
            if queried is not None:
                resolved = queried
                command_id = str(resolved.get("command_id") or "")
        known_terminal = (
            bool(resolved.get("ok"))
            and bool(command_id)
            and str(resolved.get("command_kind") or "") == command_kind
            and str(resolved.get("command_state") or "") == "completed"
            and str(resolved.get("terminal_state") or "") == terminal_state
            and not bool(resolved.get("command_state_unknown"))
        )
        if known_terminal:
            return
        safe_pending_hold_cancel = (
            command_kind == "maintenance_hold"
            and bool(command_id)
            and str(resolved.get("command_state") or "") == "cancelled"
            and not bool(resolved.get("command_state_unknown"))
        )
        raise CollectorCommandNotAcknowledgedError(
            f"collector_{command_kind}_not_acknowledged",
            fail_closed=not safe_pending_hold_cancel,
        )

    @staticmethod
    def _persist_fail_closed(*, reason: str, command: str) -> None:
        set_settings(
            {
                "user_paused": "true",
                "collector_status": "paused",
                "maintenance_fail_closed": "true",
                "maintenance_fail_closed_reason": f"{reason}_{command}",
            }
        )
        clear_runtime_activity_state(f"{reason}_{command}_fail_closed")

    @staticmethod
    def _restore_durable_state(state: RuntimeMaintenanceState) -> None:
        if state.user_paused:
            collector_status = "paused"
        elif not state.privacy_notice_accepted:
            collector_status = "stopped"
        elif state.collector_running:
            collector_status = "running"
        elif state.collector_status in {"stopped", "error", "paused"}:
            collector_status = state.collector_status
        else:
            collector_status = "stopped"
        set_settings(
            {
                "user_paused": "true" if state.user_paused else "false",
                "collector_status": collector_status,
                "maintenance_fail_closed": "false",
                "maintenance_fail_closed_reason": "",
            }
        )

    @contextmanager
    def _maintain(
        self,
        *,
        intent: MaintenanceIntent,
        reason: str,
        timeout_seconds: float,
    ) -> Iterator[RuntimeMaintenanceState]:
        if self.blocked_reason is not None:
            raise MaintenanceInProgressError("maintenance_failed_closed")
        if not self._operation_lock.acquire(blocking=False):
            raise MaintenanceInProgressError("maintenance_operation_in_progress")

        state: RuntimeMaintenanceState | None = None
        control: RuntimeMaintenanceControl | None = None
        hold_acquired = False
        operation_started = False
        operation_committed = False
        try:
            if self.blocked_reason is not None:
                raise MaintenanceInProgressError("maintenance_failed_closed")
            control = self._control()
            state = self._capture_state(control)
            self._set_phase(MaintenancePhase.HOLD_REQUESTED)
            if state.collector_running:
                if control is None:
                    raise CollectorCommandNotAcknowledgedError(
                        "collector_maintenance_hold_not_acknowledged",
                        fail_closed=True,
                    )
                hold_result = dict(
                    control.quiesce_collection_for_maintenance(
                        timeout_seconds=timeout_seconds
                    )
                )
                self._require_ack(
                    hold_result,
                    control=control,
                    command_kind="maintenance_hold",
                    terminal_state="held",
                    reason=reason,
                )
                hold_acquired = True
            self._set_phase(MaintenancePhase.HELD)
            clear_runtime_activity_state(f"{reason}_held")

            self._set_phase(MaintenancePhase.DRAINING)
            with DATABASE_WRITE_GATE.draining() as lease:
                drain_existing_writers()
                lease.promote()
                self._set_phase(MaintenancePhase.EXCLUSIVE)
                operation_started = intent is MaintenanceIntent.DATABASE_REPLACEMENT
                yield state
            operation_committed = True

            if (
                intent is MaintenanceIntent.DATABASE_REPLACEMENT
                and hold_acquired
                and control is not None
            ):
                self._set_phase(MaintenancePhase.RESETTING)
                reset_result = dict(
                    control.reset_after_database_replacement(
                        timeout_seconds=timeout_seconds
                    )
                )
                self._require_ack(
                    reset_result,
                    control=control,
                    command_kind="database_reset",
                    terminal_state="held",
                    reason=reason,
                )

            self._set_phase(MaintenancePhase.RESTORING)
            self._restore_durable_state(state)

            if hold_acquired and control is not None:
                self._set_phase(MaintenancePhase.RELEASING)
                release_result = dict(
                    control.restore_after_maintenance(
                        state,
                        timeout_seconds=timeout_seconds,
                    )
                )
                self._require_ack(
                    release_result,
                    control=control,
                    command_kind="maintenance_release",
                    terminal_state="operational",
                    reason=reason,
                )
        except Exception as exc:
            should_fail_closed = (
                hold_acquired
                or operation_started
                or operation_committed
                or (
                    isinstance(exc, CollectorCommandNotAcknowledgedError)
                    and exc.fail_closed
                )
            )
            if should_fail_closed:
                command = "restore" if operation_committed else "operation"
                self._latch_fail_closed(f"{reason}_{command}")
                if state is not None:
                    try:
                        self._persist_fail_closed(reason=reason, command=command)
                    except Exception:
                        logging.exception(
                            "maintenance fail-closed persistence failed reason=%s",
                            reason,
                        )
            logging.exception(
                "runtime maintenance failed intent=%s reason=%s",
                intent.value,
                reason,
            )
            raise
        finally:
            if self.blocked_reason is None:
                self._set_phase(MaintenancePhase.IDLE)
            self._operation_lock.release()

    @contextmanager
    def consistent_snapshot(
        self,
        reason: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> Iterator[RuntimeMaintenanceState]:
        with self._maintain(
            intent=MaintenanceIntent.CONSISTENT_SNAPSHOT,
            reason=reason,
            timeout_seconds=timeout_seconds,
        ) as state:
            yield state

    @contextmanager
    def database_replacement(
        self,
        reason: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> Iterator[RuntimeMaintenanceState]:
        with self._maintain(
            intent=MaintenanceIntent.DATABASE_REPLACEMENT,
            reason=reason,
            timeout_seconds=timeout_seconds,
        ) as state:
            yield state


MAINTENANCE_COORDINATOR = RuntimeMaintenanceCoordinator()


def register_runtime_control(control: RuntimeMaintenanceControl) -> None:
    MAINTENANCE_COORDINATOR.register_runtime_control(control)


def clear_runtime_control(
    control: RuntimeMaintenanceControl | None = None,
) -> None:
    MAINTENANCE_COORDINATOR.clear_runtime_control(control)


def recover_fail_closed() -> None:
    MAINTENANCE_COORDINATOR.recover_fail_closed()


def is_maintenance_in_progress() -> bool:
    return MAINTENANCE_COORDINATOR.active()


def maintenance_status() -> MaintenanceStatus:
    return MAINTENANCE_COORDINATOR.status()


@contextmanager
def consistent_snapshot(
    reason: str = "consistent_snapshot",
    *,
    timeout_seconds: float = 5.0,
) -> Iterator[RuntimeMaintenanceState]:
    with MAINTENANCE_COORDINATOR.consistent_snapshot(
        reason,
        timeout_seconds=timeout_seconds,
    ) as state:
        yield state


@contextmanager
def database_replacement(
    reason: str,
    *,
    timeout_seconds: float = 5.0,
) -> Iterator[RuntimeMaintenanceState]:
    with MAINTENANCE_COORDINATOR.database_replacement(
        reason,
        timeout_seconds=timeout_seconds,
    ) as state:
        yield state


def clear_all_live_data() -> None:
    """Delete current content and publish replacement in one maintenance transaction."""

    with database_replacement("clear_database"):
        with DomainUnitOfWork() as uow:
            conn = uow.connection
            for table in DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")
            seed_defaults(conn)
            publish_database_replacement(conn)


__all__ = [
    "CollectorCommandNotAcknowledgedError",
    "MAINTENANCE_COORDINATOR",
    "MaintenanceInProgressError",
    "MaintenanceIntent",
    "MaintenancePhase",
    "MaintenanceRecoveryError",
    "MaintenanceStatus",
    "RuntimeMaintenanceControl",
    "RuntimeMaintenanceCoordinator",
    "RuntimeMaintenanceState",
    "clear_all_live_data",
    "clear_runtime_control",
    "consistent_snapshot",
    "database_replacement",
    "is_maintenance_in_progress",
    "maintenance_status",
    "recover_fail_closed",
    "register_runtime_control",
]
