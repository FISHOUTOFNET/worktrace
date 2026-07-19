"""Single coordinator for destructive database maintenance and replacement."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from enum import Enum
from typing import Any, Iterator

from ..db import now_str, seed_defaults
from ..domain_unit_of_work import DomainUnitOfWork
from ..write_gate import DATABASE_WRITE_GATE
from . import (
    activity_fact_repair_service,
    activity_inference_job_repository,
    history_mutation_job_service,
    startup_recovery_job_repository,
)
from .database_maintenance_barrier import drain_existing_writers
from .database_replacement_generation_service import publish_database_replacement
from .runtime_activity_state_service import clear_runtime_activity_state
from .settings_service import SettingMutationClass, set_settings

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

_POST_CLEAR_SETTINGS: dict[str, str] = {
    "user_paused": "true",
    "collector_status": "paused",
    "clipboard_capture_enabled": "false",
}


class MaintenanceInProgressError(RuntimeError):
    """Another destructive operation already owns the maintenance boundary."""


class CollectorCommandNotAcknowledgedError(RuntimeError):
    """Collector pause or reset did not reach a known successful state."""


class MaintenancePhase(str, Enum):
    IDLE = "idle"
    DRAINING = "draining"
    EXCLUSIVE = "exclusive"


class DatabaseMaintenanceCoordinator:
    """Own operation serialization, write draining, acknowledgements and phase."""

    def __init__(self) -> None:
        self._operation_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._phase = MaintenancePhase.IDLE
        self._pause_handler: Any = None
        self._reset_handler: Any = None

    def register_pause_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._pause_handler = handler

    def clear_pause_handler(self, handler: Any | None = None) -> None:
        with self._state_lock:
            if handler is None or self._pause_handler == handler:
                self._pause_handler = None

    def register_reset_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._reset_handler = handler

    def clear_reset_handler(self, handler: Any | None = None) -> None:
        with self._state_lock:
            if handler is None or self._reset_handler == handler:
                self._reset_handler = None

    @property
    def phase(self) -> MaintenancePhase:
        with self._state_lock:
            return self._phase

    def active(self) -> bool:
        return self.phase is not MaintenancePhase.IDLE or DATABASE_WRITE_GATE.active()

    @staticmethod
    def _fail_closed(*, reason: str, command: str) -> None:
        set_settings(
            {
                "user_paused": "true",
                "collector_status": "paused",
            },
            mutation_class=SettingMutationClass.OPERATIONAL,
        )
        clear_runtime_activity_state(f"{reason}_{command}_state_unknown")

    @classmethod
    def _require_ack(
        cls,
        result: dict[str, Any],
        *,
        command: str,
        reason: str,
    ) -> None:
        if bool(result.get("ok")):
            return
        if bool(result.get("command_state_unknown")):
            cls._fail_closed(reason=reason, command=command)
        raise CollectorCommandNotAcknowledgedError(
            f"collector_{command}_not_acknowledged"
        )

    @contextmanager
    def acquire(self, *, reason: str) -> Iterator[None]:
        if not self._operation_lock.acquire(blocking=False):
            raise MaintenanceInProgressError("maintenance_operation_in_progress")
        try:
            with self._state_lock:
                pause_handler = self._pause_handler
                reset_handler = self._reset_handler
            with DATABASE_WRITE_GATE.draining() as lease:
                with self._state_lock:
                    self._phase = MaintenancePhase.DRAINING
                try:
                    if pause_handler is not None:
                        self._require_ack(
                            pause_handler(timeout_seconds=5.0),
                            command="pause",
                            reason=reason,
                        )
                    if reset_handler is not None:
                        self._require_ack(
                            reset_handler(timeout_seconds=5.0),
                            command="reset",
                            reason=reason,
                        )
                    clear_runtime_activity_state(f"{reason}_guard_enter")
                    drain_existing_writers()
                    lease.promote()
                    with self._state_lock:
                        self._phase = MaintenancePhase.EXCLUSIVE
                    yield None
                    clear_runtime_activity_state(f"{reason}_success")
                except Exception:
                    clear_runtime_activity_state(f"{reason}_rollback")
                    logging.exception("database maintenance failed reason=%s", reason)
                    raise
        finally:
            with self._state_lock:
                self._phase = MaintenancePhase.IDLE
            self._operation_lock.release()


MAINTENANCE_COORDINATOR = DatabaseMaintenanceCoordinator()


def register_collector_pause_handler(handler: Any) -> None:
    MAINTENANCE_COORDINATOR.register_pause_handler(handler)


def clear_collector_pause_handler(handler: Any | None = None) -> None:
    MAINTENANCE_COORDINATOR.clear_pause_handler(handler)


def register_collector_reset_handler(handler: Any) -> None:
    MAINTENANCE_COORDINATOR.register_reset_handler(handler)


def clear_collector_reset_handler(handler: Any | None = None) -> None:
    MAINTENANCE_COORDINATOR.clear_reset_handler(handler)


def is_maintenance_in_progress() -> bool:
    return MAINTENANCE_COORDINATOR.active()


@contextmanager
def maintenance_operation(*, reason: str) -> Iterator[None]:
    with MAINTENANCE_COORDINATOR.acquire(reason=reason):
        yield None


def clear_all_worker_progress_in_transaction(conn) -> None:
    """Clear replacement-invalid durable progress through canonical owners."""

    history_mutation_job_service.clear_all_jobs_in_transaction(conn)
    activity_inference_job_repository.clear_all_jobs(conn)
    activity_fact_repair_service.clear_all_jobs_in_transaction(conn)
    startup_recovery_job_repository.clear_all_jobs(conn)


def _apply_post_clear_settings(conn) -> None:
    updated_at = now_str()
    for key, value in _POST_CLEAR_SETTINGS.items():
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, updated_at),
        )


def clear_all_live_data() -> None:
    """Delete live rows and publish replacement only after commit succeeds."""

    with maintenance_operation(reason="clear_database"):
        with DomainUnitOfWork() as uow:
            conn = uow.connection
            clear_all_worker_progress_in_transaction(conn)
            for table in _DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")
            seed_defaults(conn)
            _apply_post_clear_settings(conn)
            publish_database_replacement(conn)


__all__ = [
    "CollectorCommandNotAcknowledgedError",
    "DatabaseMaintenanceCoordinator",
    "MAINTENANCE_COORDINATOR",
    "MaintenanceInProgressError",
    "MaintenancePhase",
    "clear_all_live_data",
    "clear_all_worker_progress_in_transaction",
    "clear_collector_pause_handler",
    "clear_collector_reset_handler",
    "is_maintenance_in_progress",
    "maintenance_operation",
    "register_collector_pause_handler",
    "register_collector_reset_handler",
]
