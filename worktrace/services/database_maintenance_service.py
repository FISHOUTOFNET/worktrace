"""Single application coordinator for snapshot and replacement maintenance."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator

from ..db import get_connection, seed_defaults
from ..domain_unit_of_work import DomainUnitOfWork
from ..write_gate import DATABASE_WRITE_GATE
from . import (
    activity_fact_repair_service,
    activity_inference_job_repository,
    history_mutation_job_service,
    privacy_gate_service,
    startup_recovery_job_repository,
)
from .database_maintenance_barrier import drain_existing_writers
from .database_replacement_generation_service import (
    capture_replacement_generation_floor,
    publish_database_replacement,
)
from .runtime_activity_state_service import clear_runtime_activity_state
from .settings_service import get_bool_setting, get_setting, set_settings

_DELETE_ORDER: tuple[str, ...] = (
    "activity_resource",
    "report_session_operation_member",
    "report_mutation_request",
    "report_session_operation",
    "activity_clipboard_event",
    "activity_project_assignment",
    "folder_rule_file_index",
    "folder_rule_index_state",
    "project_rule",
    "folder_project_rule",
    "activity_log",
    "session_boundary",
    "settings",
    "project",
)


class MaintenanceInProgressError(RuntimeError):
    """Another maintenance operation already owns the application boundary."""


class CollectorCommandNotAcknowledgedError(RuntimeError):
    """A runtime maintenance command did not reach a known successful state."""


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


class RuntimeMaintenanceCoordinator:
    """Own the only maintenance state machine, lock order and failure recovery."""

    def __init__(self) -> None:
        self._operation_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._phase = MaintenancePhase.IDLE
        self._runtime_control: Any = None

    def register_runtime_control(self, control: Any) -> None:
        with self._state_lock:
            self._runtime_control = control

    def clear_runtime_control(self, control: Any | None = None) -> None:
        with self._state_lock:
            if control is None or self._runtime_control is control:
                self._runtime_control = None

    @property
    def phase(self) -> MaintenancePhase:
        with self._state_lock:
            return self._phase

    def active(self) -> bool:
        return self.phase is not MaintenancePhase.IDLE or DATABASE_WRITE_GATE.active()

    def _set_phase(self, phase: MaintenancePhase) -> None:
        with self._state_lock:
            self._phase = phase

    def _control(self) -> Any:
        with self._state_lock:
            return self._runtime_control

    @staticmethod
    def _replacement_epoch() -> int:
        conn = get_connection()
        try:
            values = capture_replacement_generation_floor(conn)
            return max((int(value) for value in values.values()), default=0)
        finally:
            conn.close()

    def _capture_state(self, control: Any) -> RuntimeMaintenanceState:
        collector_running = bool(
            control is not None
            and bool(control.is_collection_running_for_maintenance())
        )
        return RuntimeMaintenanceState(
            privacy_notice_accepted=bool(
                privacy_gate_service.is_privacy_notice_accepted()
            ),
            user_paused=get_bool_setting("user_paused", False),
            collector_running=collector_running,
            collector_status=str(get_setting("collector_status", "stopped") or "stopped"),
            runtime_generation=DATABASE_WRITE_GATE.generation(),
            replacement_epoch=self._replacement_epoch(),
        )

    @staticmethod
    def _query_command(control: Any, command_id: str) -> dict[str, Any] | None:
        channel = getattr(control, "collector_control", None)
        query = getattr(channel, "query_command", None)
        if query is None or not command_id:
            return None
        value = query(command_id)
        return dict(value) if isinstance(value, dict) else None

    @classmethod
    def _require_ack(
        cls,
        result: dict[str, Any],
        *,
        control: Any,
        command_kind: str,
        terminal_state: str,
        reason: str,
    ) -> None:
        resolved = dict(result)
        command_id = str(resolved.get("command_id") or "")
        if bool(resolved.get("command_state_unknown")):
            queried = cls._query_command(control, command_id)
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
        if bool(resolved.get("command_state_unknown")):
            cls._fail_closed(reason=reason, command=command_kind)
        raise CollectorCommandNotAcknowledgedError(
            f"collector_{command_kind}_not_acknowledged"
        )

    @staticmethod
    def _fail_closed(*, reason: str, command: str) -> None:
        set_settings(
            {
                "user_paused": "true",
                "collector_status": "paused",
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
        if not self._operation_lock.acquire(blocking=False):
            raise MaintenanceInProgressError("maintenance_operation_in_progress")

        state: RuntimeMaintenanceState | None = None
        control: Any = None
        hold_acquired = False
        operation_committed = False
        try:
            control = self._control()
            state = self._capture_state(control)
            self._set_phase(MaintenancePhase.HOLD_REQUESTED)
            if state.collector_running:
                if control is None:
                    raise CollectorCommandNotAcknowledgedError(
                        "collector_maintenance_hold_not_acknowledged"
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
        except Exception:
            self._set_phase(MaintenancePhase.FAILED_CLOSED)
            if state is not None:
                command = "restore" if operation_committed else "operation"
                try:
                    self._fail_closed(reason=reason, command=command)
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


def register_runtime_control(control: Any) -> None:
    MAINTENANCE_COORDINATOR.register_runtime_control(control)


def clear_runtime_control(control: Any | None = None) -> None:
    MAINTENANCE_COORDINATOR.clear_runtime_control(control)


def is_maintenance_in_progress() -> bool:
    return MAINTENANCE_COORDINATOR.active()


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


def clear_all_worker_progress_in_transaction(conn) -> None:
    """Clear replacement-invalid durable progress through canonical owners."""

    history_mutation_job_service.clear_all_jobs_in_transaction(conn)
    activity_inference_job_repository.clear_all_jobs(conn)
    activity_fact_repair_service.clear_all_jobs_in_transaction(conn)
    startup_recovery_job_repository.clear_all_jobs(conn)


def clear_all_live_data() -> None:
    """Delete live rows and publish replacement only after commit succeeds."""

    with database_replacement("clear_database"):
        with DomainUnitOfWork() as uow:
            conn = uow.connection
            clear_all_worker_progress_in_transaction(conn)
            for table in _DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")
            seed_defaults(conn)
            publish_database_replacement(conn)


__all__ = [
    "CollectorCommandNotAcknowledgedError",
    "MAINTENANCE_COORDINATOR",
    "MaintenanceInProgressError",
    "MaintenanceIntent",
    "MaintenancePhase",
    "RuntimeMaintenanceCoordinator",
    "RuntimeMaintenanceState",
    "clear_all_live_data",
    "clear_all_worker_progress_in_transaction",
    "clear_runtime_control",
    "consistent_snapshot",
    "database_replacement",
    "is_maintenance_in_progress",
    "register_runtime_control",
]
