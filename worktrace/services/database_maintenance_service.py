"""Single application coordinator for snapshot and replacement maintenance."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Iterator, Protocol

from ..database_content_manifest import DELETE_ORDER
from ..database_replacement_unit_of_work import DatabaseReplacementUnitOfWork
from ..db import get_connection, seed_defaults
from ..write_gate import (
    DATABASE_MAINTENANCE_ERROR,
    DATABASE_RECOVERY_ERROR,
    DATABASE_WRITE_GATE,
    WriteDrainLease,
    WriteGatePhase,
)
from . import maintenance_recovery_latch_repository
from . import privacy_gate_service
from .database_maintenance_barrier import drain_existing_writers
from .database_replacement_generation_service import (
    capture_replacement_generation_floor,
)
from .runtime_activity_state_service import clear_runtime_activity_state
from .settings_service import get_bool_setting, get_setting, set_settings

if TYPE_CHECKING:
    from ..collector.runtime_control import RuntimeCollectorControl


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


_OPERATION_PHASES = {
    MaintenancePhase.HOLD_REQUESTED,
    MaintenancePhase.HELD,
    MaintenancePhase.DRAINING,
    MaintenancePhase.EXCLUSIVE,
    MaintenancePhase.RESETTING,
    MaintenancePhase.RESTORING,
    MaintenancePhase.RELEASING,
}


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


@dataclass
class MaintenanceOperationProgress:
    """Thread-local handoff from replacement commit to the coordinator."""

    intent: MaintenanceIntent
    recovery_epoch: str | None = None
    durable_replacement_committed: bool = False


_CURRENT_MAINTENANCE_OPERATION: ContextVar[MaintenanceOperationProgress | None] = (
    ContextVar("worktrace_maintenance_operation", default=None)
)


def record_database_replacement_committed() -> bool:
    """Record the durable commit before any post-commit publication/finalization."""

    progress = _CURRENT_MAINTENANCE_OPERATION.get()
    if progress is None or progress.intent is not MaintenanceIntent.DATABASE_REPLACEMENT:
        return False
    progress.durable_replacement_committed = True
    return True


def current_maintenance_progress() -> MaintenanceOperationProgress | None:
    return _CURRENT_MAINTENANCE_OPERATION.get()


class RuntimeMaintenanceCoordinator:
    """Own the only maintenance state machine, lock order and recovery protocol."""

    def __init__(self) -> None:
        self._operation_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._phase = MaintenancePhase.IDLE
        self._runtime_control: RuntimeMaintenanceControl | None = None
        self._runtime_control_epoch = 0

    def register_runtime_control(self, control: RuntimeMaintenanceControl) -> None:
        if control is None:
            raise ValueError("runtime_maintenance_control_required")
        with self._state_lock:
            self._runtime_control = control
            self._runtime_control_epoch += 1

    def clear_runtime_control(
        self,
        control: RuntimeMaintenanceControl | None = None,
    ) -> None:
        with self._state_lock:
            if control is None or self._runtime_control is control:
                self._runtime_control = None
                self._runtime_control_epoch += 1

    @property
    def phase(self) -> MaintenancePhase:
        with self._state_lock:
            return self._phase

    @property
    def blocked_reason(self) -> str | None:
        return DATABASE_WRITE_GATE.recovery_block_reason()

    def operation_active(self) -> bool:
        return self.phase in _OPERATION_PHASES or DATABASE_WRITE_GATE.operation_active()

    def recovery_blocked(self) -> bool:
        return (
            self.phase is MaintenancePhase.FAILED_CLOSED
            or DATABASE_WRITE_GATE.recovery_blocked()
        )

    @contextmanager
    def external_runtime_mutation_guard(self) -> Iterator[None]:
        """Narrow guard for external user-initiated runtime start/resume.

        Reuses the same operation lock as destructive/snapshot maintenance so
        that active maintenance and external runtime mutation are mutually
        exclusive. The guard also rejects when the coordinator is
        recovery-blocked. Coordinator-internal recovery calls
        (``restore_after_maintenance`` -> ``start_collector``) do not pass
        through this guard and therefore cannot self-lock.
        """

        if not self._operation_lock.acquire(blocking=False):
            raise MaintenanceInProgressError(DATABASE_MAINTENANCE_ERROR)
        try:
            if self.operation_active() or self.recovery_blocked():
                raise MaintenanceInProgressError(DATABASE_RECOVERY_ERROR)
            yield
        finally:
            self._operation_lock.release()

    def status(self) -> MaintenanceStatus:
        control, _epoch = self._control_snapshot()
        try:
            collector_running = bool(
                control is not None
                and control.is_collection_running_for_maintenance()
            )
        except Exception:
            collector_running = False
        in_progress = self.operation_active()
        recovery_blocked = self.recovery_blocked()
        return MaintenanceStatus(
            maintenance_in_progress=in_progress,
            maintenance_restored=not in_progress and not recovery_blocked,
            recovery_blocked=recovery_blocked,
            blocked_reason=DATABASE_WRITE_GATE.recovery_block_reason(),
            collector_running=collector_running,
            collector_status=str(
                get_setting("collector_status", "stopped") or "stopped"
            ),
            user_paused=get_bool_setting("user_paused", False),
        )

    def _set_phase(self, phase: MaintenancePhase) -> None:
        with self._state_lock:
            self._phase = phase

    def _control_snapshot(self) -> tuple[RuntimeMaintenanceControl | None, int]:
        with self._state_lock:
            return self._runtime_control, self._runtime_control_epoch

    @staticmethod
    def _runtime_control_is_operational(control: RuntimeMaintenanceControl) -> bool:
        try:
            return control.collector_control.hold_state.value == "operational"
        except Exception:
            logging.warning(
                "runtime maintenance control state read failed phase=verification"
            )
            return False

    def hydrate_fail_closed_from_durable(self) -> bool:
        """Hydrate the process barrier before recovery or writer startup."""

        latch = maintenance_recovery_latch_repository.read_latch()
        if not latch.blocked:
            return False
        reason = latch.reason or DATABASE_RECOVERY_ERROR
        DATABASE_WRITE_GATE._set_recovery_block(reason)
        self._set_phase(MaintenancePhase.FAILED_CLOSED)
        return True

    def _require_no_durable_recovery_block(self) -> None:
        latch = maintenance_recovery_latch_repository.read_latch()
        if not latch.blocked:
            return
        reason = latch.reason or DATABASE_RECOVERY_ERROR
        DATABASE_WRITE_GATE._set_recovery_block(reason)
        self._set_phase(MaintenancePhase.FAILED_CLOSED)
        raise MaintenanceInProgressError(DATABASE_RECOVERY_ERROR)

    def _persist_fail_closed(
        self,
        reason: str,
        *,
        recovery_epoch: str | None,
    ) -> None:
        try:
            with DATABASE_WRITE_GATE._maintenance_recovery_write_scope():
                maintenance_recovery_latch_repository.persist_fail_closed(
                    reason,
                    expected_epoch=recovery_epoch,
                )
        except Exception:
            # The armed sidecar remains authoritative even if the SQLite mirror
            # cannot be written. But without an armed epoch or sensitive staging
            # residue there is no durable evidence — the exception must propagate.
            if recovery_epoch is None:
                evidence = maintenance_recovery_latch_repository.read_latch()
                if (
                    not evidence.marker_present
                    and not evidence.sensitive_residue_present
                ):
                    raise
            logging.warning(
                "maintenance fail-closed persistence failed phase=seal"
            )

    def _enter_fail_closed(
        self,
        reason: str,
        *,
        lease: WriteDrainLease | None = None,
        recovery_epoch: str | None = None,
    ) -> None:
        normalized = str(reason or DATABASE_RECOVERY_ERROR).strip()
        if lease is not None:
            try:
                lease.handoff_to_recovery_block(normalized)
            except Exception:
                DATABASE_WRITE_GATE._set_recovery_block(normalized)
        else:
            DATABASE_WRITE_GATE._set_recovery_block(normalized)
        self._set_phase(MaintenancePhase.FAILED_CLOSED)
        try:
            clear_runtime_activity_state(f"{normalized}_fail_closed")
        except Exception:
            logging.warning(
                "runtime activity cleanup failed phase=fail_closed"
            )
        self._persist_fail_closed(
            normalized,
            recovery_epoch=recovery_epoch,
        )

    def enter_fail_closed(self, reason: str) -> None:
        """Public handoff for a security cleanup failure outside an active scope."""

        with self._operation_lock:
            self._enter_fail_closed(str(reason or DATABASE_RECOVERY_ERROR))

    def recover_fail_closed(self) -> None:
        """Clear the exact durable epoch only after stable runtime verification."""

        with self._operation_lock:
            if DATABASE_WRITE_GATE.operation_active():
                raise MaintenanceRecoveryError("maintenance_recovery_not_verified")

            latch = maintenance_recovery_latch_repository.read_latch()
            if not latch.blocked and self.phase is not MaintenancePhase.FAILED_CLOSED:
                return
            reason = latch.reason or "maintenance_recovery_state_inconsistent"
            DATABASE_WRITE_GATE._set_recovery_block(reason)
            self._set_phase(MaintenancePhase.FAILED_CLOSED)

            # Sensitive staging residue is durable recovery evidence on its
            # own. Clear it first; if it cannot be removed the process remains
            # fail-closed. Only after residue is gone do we process the
            # sidecar/mirror.
            if latch.sensitive_residue_present:
                if not maintenance_recovery_latch_repository.clear_sensitive_staging_residue():
                    raise MaintenanceRecoveryError(
                        "maintenance_recovery_not_verified"
                    )
                latch = maintenance_recovery_latch_repository.read_latch()
                if not latch.blocked:
                    DATABASE_WRITE_GATE._clear_recovery_block()
                    self._set_phase(MaintenancePhase.IDLE)
                    return
                reason = latch.reason or reason

            if not latch.epoch:
                try:
                    with DATABASE_WRITE_GATE._maintenance_recovery_write_scope():
                        latch = maintenance_recovery_latch_repository.seal_legacy_latch(
                            reason
                        )
                except Exception as exc:
                    raise MaintenanceRecoveryError(
                        "maintenance_recovery_not_verified"
                    ) from exc
            assert latch.epoch is not None

            control, control_epoch = self._control_snapshot()
            if control is None or not self._runtime_control_is_operational(control):
                raise MaintenanceRecoveryError("maintenance_recovery_not_verified")

            try:
                with self._state_lock:
                    superseded = (
                        self._runtime_control is not control
                        or self._runtime_control_epoch != control_epoch
                    )
                    operational = self._runtime_control_is_operational(control)
                    if superseded:
                        raise MaintenanceRecoveryError(
                            "maintenance_recovery_superseded"
                        )
                    if not operational:
                        raise MaintenanceRecoveryError(
                            "maintenance_recovery_not_verified"
                        )
                    with DATABASE_WRITE_GATE._maintenance_recovery_write_scope():
                        maintenance_recovery_latch_repository.clear_latch(
                            expected_epoch=latch.epoch
                        )
                    DATABASE_WRITE_GATE._clear_recovery_block()
                    self._phase = MaintenancePhase.IDLE
            except MaintenanceRecoveryError:
                raise
            except Exception as exc:
                # Marker deletion is the final durable step. Any failure leaves
                # either the sidecar or process block in place.
                raise MaintenanceRecoveryError(
                    "maintenance_recovery_not_verified"
                ) from exc

    @staticmethod
    def _replacement_epoch() -> int:
        conn = get_connection()
        try:
            values = capture_replacement_generation_floor(conn)
            return max((int(value) for value in values.values()), default=0)
        finally:
            try:
                conn.close()
            except Exception:
                logging.warning(
                    "maintenance state connection close failed phase=capture"
                )

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

    def _restore_durable_state_before_release(
        self,
        state: RuntimeMaintenanceState,
    ) -> None:
        self._set_phase(MaintenancePhase.RESTORING)
        self._restore_durable_state(state)

    def _release_and_verify_runtime(
        self,
        *,
        control: RuntimeMaintenanceControl,
        state: RuntimeMaintenanceState,
        timeout_seconds: float,
    ) -> None:
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
        )

    def _reset_after_replacement(
        self,
        *,
        control: RuntimeMaintenanceControl | None,
        timeout_seconds: float,
    ) -> None:
        if control is None:
            raise CollectorCommandNotAcknowledgedError(
                "collector_database_reset_not_acknowledged",
                fail_closed=True,
            )
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
        )

    def _verify_stable_runtime_and_clear_seal(
        self,
        *,
        control: RuntimeMaintenanceControl | None,
        control_epoch: int,
        recovery_epoch: str | None,
    ) -> None:
        if recovery_epoch is None:
            return
        with self._state_lock:
            if (
                self._runtime_control is not control
                or self._runtime_control_epoch != control_epoch
            ):
                raise MaintenanceRecoveryError("maintenance_recovery_superseded")
            if control is not None and not self._runtime_control_is_operational(control):
                raise MaintenanceRecoveryError("maintenance_recovery_not_verified")
            with DATABASE_WRITE_GATE._maintenance_recovery_write_scope():
                maintenance_recovery_latch_repository.clear_latch(
                    expected_epoch=recovery_epoch
                )

    @staticmethod
    def _requires_fail_closed(exc: BaseException) -> bool:
        if isinstance(exc, CollectorCommandNotAcknowledgedError):
            return exc.fail_closed
        return bool(getattr(exc, "requires_recovery_block", False))

    def _restore_after_failure(
        self,
        *,
        state: RuntimeMaintenanceState | None,
        control: RuntimeMaintenanceControl | None,
        control_epoch: int,
        hold_acquired: bool,
        replacement_committed: bool,
        recovery_epoch: str | None,
        requires_block: bool,
        timeout_seconds: float,
    ) -> bool:
        """Restore runtime for the non-fail-closed path.

        When ``requires_block`` is True the caller has already classified the
        exception as fail-closed. Per the maintenance contract the collector
        must remain HELD, ``restore_after_maintenance`` must not be invoked and
        the recovery seal must not be cleared. Only the optional database reset
        for a durably-committed replacement is permitted. This method returns
        False so the caller enters fail-closed.
        """

        if state is None:
            return False
        if requires_block:
            if replacement_committed:
                try:
                    self._reset_after_replacement(
                        control=control,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception:
                    logging.warning(
                        "maintenance reset failed phase=fail_closed_setup"
                    )
            return False
        try:
            if replacement_committed:
                self._reset_after_replacement(
                    control=control,
                    timeout_seconds=timeout_seconds,
                )
            self._restore_durable_state_before_release(state)
            if hold_acquired and control is not None:
                self._release_and_verify_runtime(
                    control=control,
                    state=state,
                    timeout_seconds=timeout_seconds,
                )
            self._verify_stable_runtime_and_clear_seal(
                control=control,
                control_epoch=control_epoch,
                recovery_epoch=recovery_epoch,
            )
            return True
        except Exception:
            logging.warning(
                "maintenance recovery verification failed phase=exception"
            )
            return False

    def _finalize_failure_inside_exclusive(
        self,
        *,
        exc: BaseException,
        reason: str,
        state: RuntimeMaintenanceState | None,
        control: RuntimeMaintenanceControl | None,
        control_epoch: int,
        hold_acquired: bool,
        progress: MaintenanceOperationProgress,
        lease: WriteDrainLease,
        timeout_seconds: float,
    ) -> None:
        """Recover from a body exception while still inside the EXCLUSIVE scope.

        The EXCLUSIVE write gate lease is still held so the recovery actions
        (durable restore, collector release, seal verification) run under the
        same protection as the operation body. The fail-closed path hands the
        lease to the recovery block without releasing the collector.
        """

        requires_block = self._requires_fail_closed(exc)
        replacement_committed = progress.durable_replacement_committed
        recovery_epoch = progress.recovery_epoch

        if requires_block:
            if replacement_committed:
                try:
                    self._reset_after_replacement(
                        control=control,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception:
                    logging.warning(
                        "maintenance reset failed phase=fail_closed_exclusive"
                    )
            self._enter_fail_closed(
                f"{reason}_operation",
                lease=lease,
                recovery_epoch=recovery_epoch,
            )
            return

        restored = self._restore_after_failure(
            state=state,
            control=control,
            control_epoch=control_epoch,
            hold_acquired=hold_acquired,
            replacement_committed=replacement_committed,
            recovery_epoch=recovery_epoch,
            requires_block=False,
            timeout_seconds=timeout_seconds,
        )
        if not restored:
            self._enter_fail_closed(
                f"{reason}_restore",
                lease=lease,
                recovery_epoch=recovery_epoch,
            )

    @contextmanager
    def _maintain(
        self,
        *,
        intent: MaintenanceIntent,
        reason: str,
        timeout_seconds: float,
    ) -> Iterator[RuntimeMaintenanceState]:
        if self.recovery_blocked():
            raise MaintenanceInProgressError(DATABASE_RECOVERY_ERROR)
        if not self._operation_lock.acquire(blocking=False):
            raise MaintenanceInProgressError(DATABASE_MAINTENANCE_ERROR)

        state: RuntimeMaintenanceState | None = None
        control: RuntimeMaintenanceControl | None = None
        control_epoch = 0
        hold_acquired = False
        body_returned = False
        progress = MaintenanceOperationProgress(intent=intent)
        progress_token: Token[MaintenanceOperationProgress | None] | None = None
        # Tracks whether a failure inside EXCLUSIVE scope has been
        # finalized (via _finalize_failure_inside_exclusive or post-body
        # fail-closed handoff). Outer except skips recovery when True;
        # runs it when False even if draining lease was acquired.
        exclusive_finalization_completed = False
        try:
            if self.recovery_blocked():
                raise MaintenanceInProgressError(DATABASE_RECOVERY_ERROR)
            self._require_no_durable_recovery_block()
            control, control_epoch = self._control_snapshot()
            state = self._capture_state(control)
            if intent is MaintenanceIntent.DATABASE_REPLACEMENT:
                seal = maintenance_recovery_latch_repository.arm_recovery(reason)
                progress.recovery_epoch = seal.epoch
            progress_token = _CURRENT_MAINTENANCE_OPERATION.set(progress)

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
                )
                hold_acquired = True
            self._set_phase(MaintenancePhase.HELD)
            clear_runtime_activity_state(f"{reason}_held")

            self._set_phase(MaintenancePhase.DRAINING)
            with DATABASE_WRITE_GATE.draining() as lease:
                drain_existing_writers()
                lease.promote()
                self._set_phase(MaintenancePhase.EXCLUSIVE)
                body_exception: BaseException | None = None
                try:
                    yield state
                    body_returned = True
                except BaseException as exc:
                    body_exception = exc

                if body_exception is not None:
                    # Finalize inside the EXCLUSIVE scope so the lease is still
                    # held for restore/release/seal verification. The fail-closed
                    # path hands the lease to the recovery block without
                    # releasing the collector.
                    self._finalize_failure_inside_exclusive(
                        exc=body_exception,
                        reason=reason,
                        state=state,
                        control=control,
                        control_epoch=control_epoch,
                        hold_acquired=hold_acquired,
                        progress=progress,
                        lease=lease,
                        timeout_seconds=timeout_seconds,
                    )
                    exclusive_finalization_completed = True
                    logging.warning(
                        "runtime maintenance failed intent=%s phase=%s exception=%s",
                        intent.value,
                        self.phase.value,
                        type(body_exception).__name__,
                    )
                    raise body_exception

                try:
                    if intent is MaintenanceIntent.DATABASE_REPLACEMENT:
                        # A normally returned replacement scope preserves the prior
                        # reset contract even for test/no-op bodies. A caller error
                        # after commit uses the explicit progress handoff instead.
                        self._reset_after_replacement(
                            control=control,
                            timeout_seconds=timeout_seconds,
                        )
                    self._restore_durable_state_before_release(state)
                    if hold_acquired and control is not None:
                        self._release_and_verify_runtime(
                            control=control,
                            state=state,
                            timeout_seconds=timeout_seconds,
                        )
                    self._verify_stable_runtime_and_clear_seal(
                        control=control,
                        control_epoch=control_epoch,
                        recovery_epoch=progress.recovery_epoch,
                    )
                except BaseException as post_body_exc:
                    # The body completed but the post-body recovery (reset,
                    # restore, release or seal verification) failed. Enter
                    # fail-closed directly with the EXCLUSIVE lease still held.
                    # Do not re-run the recovery actions; they already failed.
                    logging.warning(
                        "runtime maintenance recovery failed intent=%s phase=%s exception=%s",
                        intent.value,
                        self.phase.value,
                        type(post_body_exc).__name__,
                    )
                    self._enter_fail_closed(
                        f"{reason}_restore",
                        lease=lease,
                        recovery_epoch=progress.recovery_epoch,
                    )
                    exclusive_finalization_completed = True
                    raise post_body_exc
        except BaseException as exc:
            # Setup/DRAINING/promote failures never reached EXCLUSIVE
            # finalization, so restore collector hold, durable intent,
            # runtime snapshot and recovery seal via the standard path.
            # Unverifiable restore enters the existing fail-closed state.
            if not exclusive_finalization_completed:
                requires_block = self._requires_fail_closed(exc)
                restored = self._restore_after_failure(
                    state=state,
                    control=control,
                    control_epoch=control_epoch,
                    hold_acquired=hold_acquired,
                    replacement_committed=progress.durable_replacement_committed,
                    recovery_epoch=progress.recovery_epoch,
                    requires_block=requires_block,
                    timeout_seconds=timeout_seconds,
                )
                must_block = requires_block or not restored
                if must_block:
                    command = (
                        "restore"
                        if body_returned or progress.durable_replacement_committed
                        else "operation"
                    )
                    self._enter_fail_closed(
                        f"{reason}_{command}",
                        lease=None,
                        recovery_epoch=progress.recovery_epoch,
                    )
            logging.warning(
                "runtime maintenance failed intent=%s phase=%s exception=%s",
                intent.value,
                self.phase.value,
                type(exc).__name__,
            )
            raise
        finally:
            if progress_token is not None:
                try:
                    _CURRENT_MAINTENANCE_OPERATION.reset(progress_token)
                except Exception:
                    logging.warning(
                        "maintenance context reset failed phase=finalization"
                    )
            if not self.recovery_blocked():
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


def hydrate_fail_closed_from_durable() -> bool:
    return MAINTENANCE_COORDINATOR.hydrate_fail_closed_from_durable()


def recover_fail_closed() -> None:
    MAINTENANCE_COORDINATOR.recover_fail_closed()


def enter_fail_closed(reason: str) -> None:
    MAINTENANCE_COORDINATOR.enter_fail_closed(reason)


def is_maintenance_in_progress() -> bool:
    return MAINTENANCE_COORDINATOR.operation_active()


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
        with DatabaseReplacementUnitOfWork() as replacement_uow:
            conn = replacement_uow.connection
            for table in DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")
            seed_defaults(conn)


__all__ = [
    "CollectorCommandNotAcknowledgedError",
    "MAINTENANCE_COORDINATOR",
    "MaintenanceInProgressError",
    "MaintenanceIntent",
    "MaintenanceOperationProgress",
    "MaintenancePhase",
    "MaintenanceRecoveryError",
    "MaintenanceStatus",
    "RuntimeMaintenanceControl",
    "RuntimeMaintenanceCoordinator",
    "RuntimeMaintenanceState",
    "clear_all_live_data",
    "clear_runtime_control",
    "consistent_snapshot",
    "current_maintenance_progress",
    "database_replacement",
    "enter_fail_closed",
    "hydrate_fail_closed_from_durable",
    "is_maintenance_in_progress",
    "maintenance_status",
    "record_database_replacement_committed",
    "recover_fail_closed",
    "register_runtime_control",
]
