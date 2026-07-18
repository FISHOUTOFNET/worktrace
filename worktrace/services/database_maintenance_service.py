"""Single coordinator for destructive database maintenance and replacement."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator

from ..db import now_str, seed_defaults
from ..domain_unit_of_work import DomainUnitOfWork
from ..write_gate import DATABASE_WRITE_GATE
from .database_maintenance_barrier import drain_existing_writers
from .database_replacement_generation_service import publish_database_replacement
from .runtime_activity_state_service import clear_runtime_activity_state
from .settings_service import get_bool_setting, get_setting, set_setting

_DELETE_ORDER: tuple[str, ...] = (
    "activity_inference_job",
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


class MaintenancePhase(str, Enum):
    IDLE = "idle"
    DRAINING = "draining"
    EXCLUSIVE = "exclusive"


@dataclass
class MaintenanceState:
    prior_user_paused: bool
    prior_collector_status: str
    succeeded: bool = False
    fail_closed: bool = False

    def mark_succeeded(self) -> None:
        self.succeeded = True


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
    def _require_ack(
        result: dict[str, Any],
        *,
        command: str,
        reason: str,
        state: MaintenanceState,
    ) -> None:
        if bool(result.get("ok")):
            return
        if bool(result.get("command_state_unknown")):
            state.fail_closed = True
            set_setting("user_paused", "true")
            set_setting("collector_status", "paused")
            clear_runtime_activity_state(f"{reason}_{command}_state_unknown")
        raise RuntimeError(f"collector_{command}_not_acknowledged")

    @contextmanager
    def acquire(self, *, reason: str) -> Iterator[MaintenanceState]:
        if not self._operation_lock.acquire(blocking=False):
            raise MaintenanceInProgressError("maintenance_operation_in_progress")
        try:
            with self._state_lock:
                pause_handler = self._pause_handler
                reset_handler = self._reset_handler
            with DATABASE_WRITE_GATE.draining() as lease:
                with self._state_lock:
                    self._phase = MaintenancePhase.DRAINING
                prior_user_paused = get_bool_setting("user_paused", False)
                prior_collector_status = get_setting("collector_status", "stopped") or "stopped"
                state = MaintenanceState(
                    prior_user_paused=prior_user_paused,
                    prior_collector_status=prior_collector_status,
                )
                try:
                    if pause_handler is not None:
                        self._require_ack(
                            pause_handler(timeout_seconds=5.0),
                            command="pause",
                            reason=reason,
                            state=state,
                        )
                    if reset_handler is not None:
                        self._require_ack(
                            reset_handler(timeout_seconds=5.0),
                            command="reset",
                            reason=reason,
                            state=state,
                        )
                    set_setting("user_paused", "true")
                    set_setting("collector_status", "paused")
                    clear_runtime_activity_state(f"{reason}_guard_enter")
                    drain_existing_writers()
                    lease.promote()
                    with self._state_lock:
                        self._phase = MaintenancePhase.EXCLUSIVE
                    yield state
                    state.succeeded = True
                    clear_runtime_activity_state(f"{reason}_success")
                except Exception:
                    if not state.succeeded and not state.fail_closed:
                        set_setting(
                            "user_paused",
                            "true" if prior_user_paused else "false",
                        )
                        set_setting("collector_status", prior_collector_status)
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
def maintenance_operation(*, reason: str) -> Iterator[MaintenanceState]:
    with MAINTENANCE_COORDINATOR.acquire(reason=reason) as state:
        yield state


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
    """Delete live rows and publish replacement only after the transaction succeeds."""

    with maintenance_operation(reason="clear_database") as state:
        with DomainUnitOfWork() as uow:
            conn = uow.connection
            for table in _DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM activity_resource_repair_job")
            seed_defaults(conn)
            _apply_post_clear_settings(conn)
            publish_database_replacement(conn)
        state.mark_succeeded()


__all__ = [
    "DatabaseMaintenanceCoordinator",
    "MAINTENANCE_COORDINATOR",
    "MaintenanceInProgressError",
    "MaintenancePhase",
    "MaintenanceState",
    "clear_all_live_data",
    "clear_collector_pause_handler",
    "clear_collector_reset_handler",
    "is_maintenance_in_progress",
    "maintenance_operation",
    "register_collector_pause_handler",
    "register_collector_reset_handler",
]
