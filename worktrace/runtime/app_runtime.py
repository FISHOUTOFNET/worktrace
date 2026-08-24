"""Process-level owner for the complete WorkTrace application runtime."""
from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable

from .. import db
from ..collector import collector_health
from ..collector.collector import run_collector
from ..collector.runtime_control import RuntimeCollectorControl
from ..collector.single_instance import acquire_single_instance, release_single_instance
from ..platforms.base import RuntimePlatformAdapter
from ..platforms.windows_adapter import WindowsAdapter
from ..services import (
    activity_fact_repair_service,
    activity_inference_job_service,
    activity_lifecycle_service,
    database_maintenance_service,
    folder_index_service,
    history_mutation_job_service,
    project_inference_service,
    recovery_service,
    runtime_activity_state_service,
)
from ..services.settings_service import set_setting
from ..worker_health import WorkerHealthRegistry, WorkerHealthReporter
from .collector_supervisor import CollectorSupervisor
from .contracts import RuntimeStartResult as _RuntimeStartResult
from .contracts import WorkerStartupState as _WorkerStartupState
from .contracts import WorkerStartupStatus as _WorkerStartupStatus

if TYPE_CHECKING:
    class _Paths:
        db_path: str
        log_path: str

    _Paths = _Paths  # noqa: F811


_WORKER_RESTART_INITIAL_SECONDS = 1.0
_WORKER_RESTART_MAX_SECONDS = 30.0
_WORKER_STABLE_RUN_SECONDS = 30.0
_COLLECTOR_LIVE_FRESHNESS_SECONDS = 8.0
_COLLECTOR_STALL_SECONDS = 180.0
_COLLECTOR_STALL_LOG_INTERVAL_SECONDS = 60.0


class RuntimePhase(str, Enum):
    NEW = "new"
    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    RECOVERABLE_FAILURE = "recoverable_failure"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    thread_name: str
    target: Callable[..., None]
    args_factory: Callable[[threading.Event], tuple[object, ...]]
    startup_timeout_seconds: float = 5.0
    critical: bool = False


@dataclass
class WorkerHandle:
    spec: WorkerSpec
    thread: threading.Thread | None
    stop_event: threading.Event
    ready_event: threading.Event = field(default_factory=threading.Event)
    failed_event: threading.Event = field(default_factory=threading.Event)
    serving_event: threading.Event = field(default_factory=threading.Event)
    error_code: str | None = None


class WorkerStartupReporter:
    """One-shot startup handshake owned by a worker invocation."""

    def __init__(self, handle: WorkerHandle) -> None:
        self._handle = handle
        self._lock = threading.Lock()

    @property
    def ready_reported(self) -> bool:
        return self._handle.ready_event.is_set()

    @property
    def failed_reported(self) -> bool:
        return self._handle.failed_event.is_set()

    def ready(self) -> None:
        with self._lock:
            if not self._handle.failed_event.is_set():
                self._handle.ready_event.set()

    def failed(self, code: str) -> None:
        with self._lock:
            if self._handle.ready_event.is_set():
                return
            self._handle.error_code = str(code or "worker_startup_failed")
            self._handle.failed_event.set()


class _OwnedWorkerReporter:
    """Worker-facing iteration health capability, separate from startup readiness."""

    def __init__(
        self,
        health: WorkerHealthReporter,
        handle: WorkerHandle,
        on_health_change: Callable[[], None],
    ) -> None:
        self._health = health
        self._handle = handle
        self._on_health_change = on_health_change
        self.name = health.name

    def succeeded(self) -> None:
        self._handle.serving_event.set()
        self._health.succeeded()
        self._on_health_change()

    def failed(self, code: str) -> None:
        self._health.failed(code)
        self._on_health_change()

    def maintenance_paused(self, paused: bool) -> None:
        paused = bool(paused)
        self._health.maintenance_paused(paused)
        if paused:
            self._handle.serving_event.set()
            self._on_health_change()


@dataclass(frozen=True)
class WorkerStartupReport:
    workers: dict[str, _WorkerStartupStatus]
    error_code: str | None = None

    @property
    def ready(self) -> bool:
        return all(status.ready for status in self.workers.values())

    @property
    def started_any(self) -> bool:
        return any(status.started for status in self.workers.values())

    @property
    def failed_workers(self) -> tuple[str, ...]:
        return tuple(name for name, status in self.workers.items() if not status.ready)


def _choose_adapter() -> RuntimePlatformAdapter:
    if not sys.platform.startswith("win"):
        raise RuntimeError("unsupported_platform")
    return WindowsAdapter()


def _thread_is_alive(thread: threading.Thread | None) -> bool:
    return thread is not None and thread in threading.enumerate()


class AppRuntime:
    """Single owner for instance, adapter, Collector and worker lifecycles."""

    def __init__(
        self,
        paths: "_Paths",
        adapter: RuntimePlatformAdapter | None = None,
    ) -> None:
        self.paths = paths
        self.stop_event = threading.Event()
        self.owns_application_instance = False
        self.collector_control = RuntimeCollectorControl()
        self.phase = RuntimePhase.NEW
        self._lifecycle_lock = threading.RLock()
        self._adapter = adapter if adapter is not None else _choose_adapter()
        self._worker_health = WorkerHealthRegistry()
        self._collector_thread: threading.Thread | None = None
        self._collector_stop_event: threading.Event | None = None
        self._collector_generation = 0
        self._collector_ready_generation = 0
        self._collector_terminal_generation = 0
        self._collector_terminal_reason = ""
        self._collector_recovery_required_reason = ""
        self._last_collector_stall_log_monotonic = 0.0
        self._worker_handles: dict[str, WorkerHandle] = {}
        self.collector_supervisor = CollectorSupervisor(self)
        self._worker_specs = self._build_worker_specs()
        self._initialized = False
        self._shutdown = False

    def _build_worker_specs(self) -> dict[str, WorkerSpec]:
        return {
            "clipboard_capture": WorkerSpec(
                name="clipboard_capture",
                thread_name="WorkTraceClipboardCapture",
                target=self._adapter.run_clipboard_capture,
                args_factory=lambda stop: (stop,),
            ),
            "folder_index": WorkerSpec(
                name="folder_index",
                thread_name="WorkTraceFolderIndex",
                target=folder_index_service.run_folder_index_worker,
                args_factory=lambda stop: (stop,),
            ),
            "history": WorkerSpec(
                name="history",
                thread_name="WorkTraceHistoryMutation",
                target=history_mutation_job_service.run_history_worker,
                args_factory=lambda stop: (stop,),
            ),
            "inference": WorkerSpec(
                name="inference",
                thread_name="WorkTraceInferenceWorker",
                target=activity_inference_job_service.run_inference_worker,
                args_factory=lambda stop: (
                    stop,
                    project_inference_service.assign_project_for_activity_in_transaction,
                ),
            ),
            "activity_resource_repair": WorkerSpec(
                name="activity_resource_repair",
                thread_name="WorkTraceActivityResourceRepair",
                target=activity_fact_repair_service.run_activity_resource_repair_worker,
                args_factory=lambda stop: (stop,),
            ),
            "startup_recovery": WorkerSpec(
                name="startup_recovery",
                thread_name="WorkTraceStartupRecovery",
                target=recovery_service.run_startup_recovery_worker,
                args_factory=lambda stop: (stop,),
            ),
            "collector_supervisor": WorkerSpec(
                name="collector_supervisor",
                thread_name="WorkTraceCollectorSupervisor",
                target=self.collector_supervisor.run_worker,
                args_factory=lambda stop: (stop,),
            ),
        }

    def initialize(self) -> bool:
        with self._lifecycle_lock:
            if self._initialized:
                return self.owns_application_instance
            if self._shutdown:
                return False
            self.owns_application_instance = acquire_single_instance()
            if not self.owns_application_instance:
                self.phase = RuntimePhase.FAILED
                logging.warning("single application instance lock not acquired; startup aborted")
                return False
            try:
                db.initialize_database(self.paths.db_path)
                database_maintenance_service.register_runtime_control(self)
                blocked = database_maintenance_service.hydrate_fail_closed_from_durable()
                if not blocked:
                    recovery_service.recover_unclosed_records()
            except Exception:
                database_maintenance_service.clear_runtime_control(self)
                release_single_instance()
                self.owns_application_instance = False
                self.phase = RuntimePhase.FAILED
                raise
            self._initialized = True
            self.phase = (
                RuntimePhase.RECOVERABLE_FAILURE
                if blocked
                else RuntimePhase.INITIALIZED
            )
            return True

    def _run_owned_worker(self, handle: WorkerHandle) -> None:
        spec = handle.spec
        health = self._worker_health.reporter(spec.name)
        startup = WorkerStartupReporter(handle)
        worker_reporter = _OwnedWorkerReporter(
            health,
            handle,
            self._reconcile_worker_health_phase,
        )
        health.started()
        startup.ready()
        restart_delay = _WORKER_RESTART_INITIAL_SECONDS
        try:
            while not handle.stop_event.is_set() and not self.stop_event.is_set():
                handle.serving_event.clear()
                invocation_started_at = time.monotonic()
                lifecycle_error: str | None = None
                try:
                    spec.target(
                        *spec.args_factory(handle.stop_event),
                        health=worker_reporter,
                    )
                    if not handle.stop_event.is_set() and not self.stop_event.is_set():
                        lifecycle_error = "worker_unexpected_exit"
                        logging.error(
                            "owned worker returned unexpectedly worker=%s",
                            spec.name,
                        )
                except Exception:
                    if not handle.stop_event.is_set() and not self.stop_event.is_set():
                        lifecycle_error = "worker_unhandled_exception"
                        logging.exception("owned worker failed worker=%s", spec.name)

                if lifecycle_error is None:
                    break

                handle.serving_event.clear()
                health.failed(lifecycle_error)
                self._mark_worker_runtime_degraded()
                if not self._owned_worker_restart_allowed(handle):
                    break

                ran_for = time.monotonic() - invocation_started_at
                if ran_for >= _WORKER_STABLE_RUN_SECONDS:
                    restart_delay = _WORKER_RESTART_INITIAL_SECONDS
                logging.warning(
                    "owned worker restart scheduled worker=%s delay_seconds=%.1f",
                    spec.name,
                    restart_delay,
                )
                if handle.stop_event.wait(restart_delay) or self.stop_event.is_set():
                    break
                restart_delay = min(
                    restart_delay * 2.0,
                    _WORKER_RESTART_MAX_SECONDS,
                )
                logging.info("owned worker restarting worker=%s", spec.name)
        finally:
            handle.serving_event.clear()
            health.stopped()
            if self.phase in {RuntimePhase.RUNNING, RuntimePhase.STARTING}:
                self.phase = RuntimePhase.DEGRADED

    def _owned_worker_restart_allowed(self, handle: WorkerHandle) -> bool:
        if handle.spec.critical:
            return False
        with self._lifecycle_lock:
            return bool(
                not self._shutdown
                and not self.stop_event.is_set()
                and not handle.stop_event.is_set()
                and handle.thread is threading.current_thread()
                and self._worker_handles.get(handle.spec.name) is handle
            )

    def _mark_worker_runtime_degraded(self) -> None:
        with self._lifecycle_lock:
            if self.phase in {RuntimePhase.RUNNING, RuntimePhase.STARTING}:
                self.phase = RuntimePhase.DEGRADED

    def _reconcile_worker_health_phase(self) -> None:
        with self._lifecycle_lock:
            if self.phase not in {
                RuntimePhase.STARTING,
                RuntimePhase.RUNNING,
                RuntimePhase.DEGRADED,
            }:
                return
            if self._shutdown or self.stop_event.is_set():
                return
            if not _thread_is_alive(self._collector_thread):
                return

            handles = tuple(self._worker_handles.values())
            if any(not _thread_is_alive(handle.thread) for handle in handles):
                self.phase = RuntimePhase.DEGRADED
                return
            if any(not handle.ready_event.is_set() for handle in handles):
                if self.phase is not RuntimePhase.STARTING:
                    self.phase = RuntimePhase.DEGRADED
                return
            if self._worker_health.degraded_workers():
                self.phase = RuntimePhase.DEGRADED
                return

            health_states = self._worker_health.snapshots()
            unserved = [
                handle
                for handle in handles
                if not handle.serving_event.is_set()
            ]
            if unserved:
                failed_before_serving = any(
                    (
                        state := health_states.get(handle.spec.name)
                    ) is not None
                    and state.consecutive_failures > 0
                    for handle in unserved
                )
                if failed_before_serving or self.phase is RuntimePhase.DEGRADED:
                    self.phase = RuntimePhase.DEGRADED
                else:
                    self.phase = RuntimePhase.STARTING
                return

            self.phase = RuntimePhase.RUNNING

    def _run_owned_collector(
        self,
        generation: int,
        adapter: RuntimePlatformAdapter,
        stop_event: threading.Event,
        control: RuntimeCollectorControl,
        ready_event: threading.Event,
        failed_event: threading.Event,
    ) -> None:
        try:
            run_collector(adapter, stop_event, control, ready_event, failed_event)
        except BaseException:
            try:
                collector_health.record_unhandled_runtime_failure(db.now_str())
            except Exception as health_exc:
                logging.error(
                    "collector unhandled failure health persistence failed exception=%s",
                    type(health_exc).__name__,
                )
            try:
                collector_health.record_collector_stopped(db.now_str())
            except Exception as stop_exc:
                logging.error(
                    "collector stopped-state persistence failed exception=%s",
                    type(stop_exc).__name__,
                )
            raise
        finally:
            reason = (
                "collector_fatal_exit"
                if failed_event.is_set() or not stop_event.is_set()
                else "collector_shutdown"
            )
            try:
                runtime_activity_state_service.clear_runtime_activity_state(
                    "collector_invocation_terminated"
                )
            except Exception as clear_exc:
                logging.error(
                    "collector runtime state clear failed exception=%s",
                    type(clear_exc).__name__,
                )
            collector_health.terminalize_runtime_invocation(generation, reason)
            with self._lifecycle_lock:
                if generation == self._collector_generation:
                    self._collector_terminal_generation = generation
                    self._collector_terminal_reason = reason
                    self._collector_ready_generation = 0
            control.terminalize_unfinished(reason)

    def collection_liveness_snapshot(self) -> dict[str, object]:
        """Return the sole process-authoritative Collector live eligibility."""

        with self._lifecycle_lock:
            generation = int(self._collector_generation)
            ready_generation = int(self._collector_ready_generation)
            terminal_generation = int(self._collector_terminal_generation)
            terminal_reason = str(self._collector_terminal_reason or "")
            recovery_reason = str(self._collector_recovery_required_reason or "")
            thread = self._collector_thread
            stop_event = self._collector_stop_event
            control = self.collector_control
            owned = bool(self.owns_application_instance and not self._shutdown)
        thread_alive = _thread_is_alive(thread)
        hold_state = getattr(control, "hold_state", None)
        hold_value = str(getattr(hold_state, "value", hold_state) or "")
        progress = collector_health.runtime_progress_snapshot()
        progress_generation = int(progress.get("generation") or 0)
        runtime_status = str(progress.get("runtime_status") or "")
        last_success = str(progress.get("last_successful_observation_at") or "")
        last_monotonic = float(progress.get("last_success_monotonic") or 0.0)
        age = max(0.0, time.monotonic() - last_monotonic) if last_monotonic > 0 else None

        state = "stopped"
        live_eligible = False
        reason = terminal_reason
        if recovery_reason:
            state = "recovery_required"
            reason = recovery_reason
        elif not owned or not thread_alive:
            state = "stopped"
        elif stop_event is None or stop_event.is_set() or terminal_generation == generation:
            state = "stopped"
        elif hold_value and hold_value != "operational":
            state = "held"
            reason = hold_value
        elif ready_generation != generation or progress_generation != generation:
            state = "starting"
        elif runtime_status == "paused":
            state = "paused"
        elif runtime_status == "stopped":
            state = "stopped"
        elif age is None:
            state = "starting"
        elif age > _COLLECTOR_STALL_SECONDS:
            state = "stale"
            reason = "collector_progress_stale"
        elif age > _COLLECTOR_LIVE_FRESHNESS_SECONDS:
            state = "degraded"
            reason = "collector_progress_delayed"
        elif runtime_status == "running":
            state = "active"
            live_eligible = True
        else:
            state = "starting"

        return {
            "generation": generation,
            "state": state,
            "live_eligible": live_eligible,
            "thread_alive": thread_alive,
            "last_successful_observation_at": last_success,
            "last_progress_age_seconds": age,
            "reason": reason,
        }

    def mark_collector_recovery_required(self, reason: str) -> None:
        value = str(reason or "collector_recovery_required").strip().lower()
        value = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)
        value = value.strip("_")[:64] or "collector_recovery_required"
        with self._lifecycle_lock:
            self._collector_recovery_required_reason = value
            if self.phase not in {RuntimePhase.STOPPING, RuntimePhase.STOPPED}:
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
        collector_health.record_health_code("collector_recovery_required")

    def diagnose_stalled_collector(self) -> None:
        """Log safe source locations for an alive-but-stalled Collector."""

        now = time.monotonic()
        with self._lifecycle_lock:
            thread = self._collector_thread
            if (
                not _thread_is_alive(thread)
                or now - self._last_collector_stall_log_monotonic
                < _COLLECTOR_STALL_LOG_INTERVAL_SECONDS
            ):
                return
            self._last_collector_stall_log_monotonic = now
            ident = thread.ident if thread is not None else None
        frame = sys._current_frames().get(ident) if ident is not None else None
        locations: list[str] = []
        while frame is not None:
            normalized = str(frame.f_code.co_filename or "").replace("\\", "/")
            parts = [part for part in normalized.split("/") if part]
            safe_path = "/".join(parts[-3:]) or "unknown"
            locations.append(
                f"{safe_path}:{frame.f_lineno}:{frame.f_code.co_name}"
            )
            frame = frame.f_back
        logging.error(
            "collector stalled thread_alive=true stack=%s",
            ">".join(locations[-6:]) or "none",
        )

    def worker_health_snapshot(self) -> dict[str, object]:
        return {
            "workers": self._worker_health.public_snapshot(),
            "degraded_workers": list(self._worker_health.degraded_workers()),
        }

    def worker_registry_snapshot(self) -> dict[str, _WorkerStartupStatus]:
        with self._lifecycle_lock:
            return {
                name: self._status_for_handle(handle, started=False)
                for name, handle in self._worker_handles.items()
            }

    def _status_for_handle(
        self,
        handle: WorkerHandle,
        *,
        started: bool,
    ) -> _WorkerStartupStatus:
        alive = _thread_is_alive(handle.thread)
        ready = handle.ready_event.is_set() and alive
        if ready:
            state = _WorkerStartupState.READY
        elif handle.failed_event.is_set() or handle.error_code:
            state = _WorkerStartupState.FAILED
        elif alive:
            state = _WorkerStartupState.STARTING
        else:
            state = _WorkerStartupState.STOPPED
        return _WorkerStartupStatus(
            state=state,
            ready=ready,
            started=started,
            error_code=handle.error_code,
        )

    def _start_worker(
        self,
        spec: WorkerSpec,
    ) -> tuple[WorkerHandle | None, bool, _WorkerStartupStatus | None]:
        with self._lifecycle_lock:
            if self._shutdown or self.stop_event.is_set():
                return (
                    None,
                    False,
                    _WorkerStartupStatus(
                        _WorkerStartupState.STOPPED,
                        False,
                        started=False,
                        error_code="runtime_stopping",
                    ),
                )

            existing = self._worker_handles.get(spec.name)
            if existing is not None and _thread_is_alive(existing.thread):
                return existing, False, None
            if existing is not None:
                self._worker_handles.pop(spec.name, None)

            handle = WorkerHandle(
                spec=spec,
                thread=None,
                stop_event=threading.Event(),
            )
            thread = threading.Thread(
                target=self._run_owned_worker,
                args=(handle,),
                name=spec.thread_name,
                daemon=True,
            )
            handle.thread = thread
            self._worker_handles[spec.name] = handle
            try:
                thread.start()
            except Exception:
                handle.error_code = "worker_thread_start_failed"
                handle.failed_event.set()
                self._worker_handles.pop(spec.name, None)
                logging.exception("worker thread start failed worker=%s", spec.name)
                return (
                    None,
                    False,
                    _WorkerStartupStatus(
                        _WorkerStartupState.FAILED,
                        False,
                        started=False,
                        error_code=handle.error_code,
                    ),
                )
            return handle, True, None

    def _timeout_worker_startup(
        self,
        handle: WorkerHandle,
        *,
        started: bool,
        join_thread: bool,
    ) -> _WorkerStartupStatus:
        handle.error_code = "worker_startup_timeout"
        handle.failed_event.set()
        handle.stop_event.set()
        if join_thread and handle.thread is not None:
            handle.thread.join(timeout=1.0)
        if not _thread_is_alive(handle.thread):
            with self._lifecycle_lock:
                if self._worker_handles.get(handle.spec.name) is handle:
                    self._worker_handles.pop(handle.spec.name, None)
        return _WorkerStartupStatus(
            _WorkerStartupState.FAILED,
            False,
            started=started,
            error_code=handle.error_code,
        )

    def _await_worker_startup(
        self,
        handle: WorkerHandle,
        *,
        started: bool,
    ) -> _WorkerStartupStatus:
        deadline = time.monotonic() + max(0.1, handle.spec.startup_timeout_seconds)
        while time.monotonic() < deadline:
            if handle.ready_event.wait(timeout=0.05):
                return self._status_for_handle(handle, started=started)
            if handle.failed_event.is_set() or not _thread_is_alive(handle.thread):
                return self._status_for_handle(handle, started=started)
        return self._timeout_worker_startup(
            handle,
            started=started,
            join_thread=True,
        )

    def _await_worker_startups(
        self,
        pending: dict[str, tuple[WorkerHandle, bool, float]],
    ) -> dict[str, _WorkerStartupStatus]:
        statuses: dict[str, _WorkerStartupStatus] = {}
        while pending:
            current = time.monotonic()
            nearest_deadline: float | None = None
            for name, (handle, started, deadline) in list(pending.items()):
                if (
                    handle.ready_event.is_set()
                    or handle.failed_event.is_set()
                    or not _thread_is_alive(handle.thread)
                ):
                    statuses[name] = self._status_for_handle(
                        handle,
                        started=started,
                    )
                    pending.pop(name, None)
                    continue
                if current >= deadline:
                    statuses[name] = self._timeout_worker_startup(
                        handle,
                        started=started,
                        join_thread=False,
                    )
                    pending.pop(name, None)
                    continue
                nearest_deadline = (
                    deadline
                    if nearest_deadline is None
                    else min(nearest_deadline, deadline)
                )

            if not pending:
                break
            remaining = max(
                0.001,
                (nearest_deadline or (time.monotonic() + 0.05)) - time.monotonic(),
            )
            time.sleep(min(0.05, remaining))
        return statuses

    def _blocked_worker_report(self) -> WorkerStartupReport:
        statuses = {
            name: _WorkerStartupStatus(
                _WorkerStartupState.FAILED,
                False,
                error_code="database_maintenance_recovery_required",
            )
            for name in self._worker_specs
        }
        return WorkerStartupReport(
            statuses,
            "database_maintenance_recovery_required",
        )

    def start_background_workers(self) -> WorkerStartupReport:
        with self._lifecycle_lock:
            if database_maintenance_service.MAINTENANCE_COORDINATOR.recovery_blocked():
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
                return self._blocked_worker_report()
            if not self._initialized or not self.owns_application_instance:
                statuses = {
                    name: _WorkerStartupStatus(
                        _WorkerStartupState.FAILED,
                        False,
                        error_code="runtime_not_owned",
                    )
                    for name in self._worker_specs
                }
                return WorkerStartupReport(statuses, "runtime_not_owned")
            if self._shutdown or self.stop_event.is_set():
                statuses = {
                    name: _WorkerStartupStatus(
                        _WorkerStartupState.STOPPED,
                        False,
                        error_code="runtime_stopping",
                    )
                    for name in self._worker_specs
                }
                return WorkerStartupReport(statuses, "runtime_stopping")
            worker_specs = tuple(self._worker_specs.items())

        startup_started_at = time.monotonic()
        statuses: dict[str, _WorkerStartupStatus] = {}
        pending: dict[str, tuple[WorkerHandle, bool, float]] = {}
        for name, spec in worker_specs:
            handle, started, immediate_status = self._start_worker(spec)
            if immediate_status is not None:
                statuses[name] = immediate_status
                continue
            if handle is None:
                statuses[name] = _WorkerStartupStatus(
                    _WorkerStartupState.FAILED,
                    False,
                    started=False,
                    error_code="worker_start_failed",
                )
                continue
            pending[name] = (
                handle,
                started,
                time.monotonic() + max(0.1, spec.startup_timeout_seconds),
            )

        statuses.update(self._await_worker_startups(pending))
        ordered_statuses = {
            name: statuses[name]
            for name, _spec in worker_specs
        }
        error_code = (
            "worker_start_failed"
            if any(not status.ready for status in ordered_statuses.values())
            else None
        )
        report = WorkerStartupReport(ordered_statuses, error_code)
        logging.info(
            "background worker startup complete elapsed_ms=%s ready=%s failed=%s",
            int((time.monotonic() - startup_started_at) * 1000),
            report.ready,
            list(report.failed_workers),
        )
        return report

    def start_authorized_collection(self) -> _RuntimeStartResult:
        with self._lifecycle_lock:
            if database_maintenance_service.MAINTENANCE_COORDINATOR.recovery_blocked():
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
                return _RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    workers={},
                    degraded=True,
                    error_code="database_maintenance_recovery_required",
                )
            if self._collector_recovery_required_reason:
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
                return _RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    workers={},
                    degraded=True,
                    error_code="collector_recovery_required",
                )
            if not self._initialized or not self.owns_application_instance:
                return _RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    workers={},
                    degraded=True,
                    error_code="runtime_not_owned",
                )
            if self._shutdown or self.stop_event.is_set():
                return _RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    workers={},
                    degraded=True,
                    error_code="runtime_stopping",
                )
            self.phase = RuntimePhase.STARTING

        startup_started_at = time.monotonic()
        collector_started_at = time.monotonic()
        try:
            collector_result = self.start_collector()
        except Exception:
            logging.exception("collector startup failed")
            collector_result = {"ok": False, "error": "collector_start_failed"}
        logging.info(
            "collector startup complete elapsed_ms=%s ok=%s",
            int((time.monotonic() - collector_started_at) * 1000),
            bool(collector_result.get("ok")),
        )

        if not bool(collector_result.get("ok")):
            error_code = str(collector_result.get("error") or "collector_start_failed")
            self.phase = (
                RuntimePhase.FAILED
                if error_code in {"collector_stop_timeout", "runtime_stopping"}
                else RuntimePhase.RECOVERABLE_FAILURE
            )
            return _RuntimeStartResult(
                ok=False,
                collector_ready=False,
                workers={},
                degraded=True,
                error_code=error_code,
            )

        try:
            report = self.start_background_workers()
        except Exception:
            logging.exception("background worker startup failed")
            report = WorkerStartupReport(
                {
                    name: _WorkerStartupStatus(
                        _WorkerStartupState.FAILED,
                        False,
                        error_code="worker_start_failed",
                    )
                    for name in self._worker_specs
                },
                "worker_start_failed",
            )

        if not report.ready:
            self.phase = RuntimePhase.DEGRADED
        else:
            self._reconcile_worker_health_phase()
        degraded = self.phase is RuntimePhase.DEGRADED
        logging.info(
            "authorized runtime startup complete elapsed_ms=%s degraded=%s phase=%s",
            int((time.monotonic() - startup_started_at) * 1000),
            degraded,
            self.phase.value,
        )
        return _RuntimeStartResult(
            ok=True,
            collector_ready=True,
            workers=report.workers,
            already_running=bool(collector_result.get("already_running")),
            degraded=degraded,
            error_code=None,
        )

    def start_collector(
        self,
        *,
        startup_timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        with self._lifecycle_lock:
            if database_maintenance_service.MAINTENANCE_COORDINATOR.recovery_blocked():
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
                return {
                    "ok": False,
                    "error": "database_maintenance_recovery_required",
                }
            if self._collector_recovery_required_reason:
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
                return {"ok": False, "error": "collector_recovery_required"}
            if self._shutdown or self.stop_event.is_set():
                return {"ok": False, "error": "runtime_stopping"}
            if not self.owns_application_instance:
                return {"ok": False, "error": "collector_not_owned"}
            if _thread_is_alive(self._collector_thread):
                if self._collector_stop_event is not None and self._collector_stop_event.is_set():
                    return {"ok": False, "error": "collector_stopping"}
                database_maintenance_service.register_runtime_control(self)
                return {"ok": True, "started": False, "already_running": True}
            if self._collector_thread is not None:
                try:
                    collector_health.record_health_code("thread_dead_replaced")
                except Exception as health_exc:
                    logging.error(
                        "collector dead-thread health persistence failed exception=%s",
                        type(health_exc).__name__,
                    )
                progress = collector_health.runtime_progress_snapshot()
                safe_end_time = (
                    str(progress.get("last_successful_observation_at") or "")
                    if int(progress.get("generation") or 0)
                    == int(self._collector_generation)
                    else ""
                )
                recovery = recovery_service.recover_after_collector_crash(
                    safe_end_time or None
                )
                if not bool(recovery.get("ok")):
                    self.phase = RuntimePhase.RECOVERABLE_FAILURE
                    if not bool(recovery.get("retryable")):
                        self.mark_collector_recovery_required(
                            "crash_reconciliation_failed"
                        )
                    return {
                        "ok": False,
                        "error": str(
                            recovery.get("error") or "collector_recovery_failed"
                        ),
                        "retryable": bool(recovery.get("retryable")),
                    }
                self._collector_thread = None
                self._collector_stop_event = None
                self.collector_control = RuntimeCollectorControl()

            ready_event = threading.Event()
            failed_event = threading.Event()
            attempt_stop_event = threading.Event()
            attempt_control = RuntimeCollectorControl()
            self._collector_generation += 1
            attempt_generation = self._collector_generation
            self._collector_ready_generation = 0
            self._collector_terminal_generation = 0
            self._collector_terminal_reason = ""
            collector_health.begin_runtime_invocation(attempt_generation)
            self._collector_stop_event = attempt_stop_event
            self.collector_control = attempt_control
            try:
                thread = threading.Thread(
                    target=self._run_owned_collector,
                    args=(
                        attempt_generation,
                        self._adapter,
                        attempt_stop_event,
                        attempt_control,
                        ready_event,
                        failed_event,
                    ),
                    name="WorkTraceCollector",
                    daemon=True,
                )
                self._collector_thread = thread
                thread.start()
            except Exception:
                logging.exception("collector thread start failed")
                collector_health.terminalize_runtime_invocation(
                    attempt_generation,
                    "collector_thread_start_failed",
                )
                attempt_control.terminalize_unfinished("collector_thread_start_failed")
                self._collector_thread = None
                self._collector_stop_event = None
                self.collector_control = RuntimeCollectorControl()
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
                return {"ok": False, "error": "collector_start_failed"}

        deadline = time.monotonic() + max(0.1, float(startup_timeout_seconds))
        startup_ready = False
        while time.monotonic() < deadline:
            if ready_event.wait(timeout=0.05):
                startup_ready = True
                break
            if failed_event.is_set() or not _thread_is_alive(thread):
                break

        if startup_ready:
            with self._lifecycle_lock:
                if (
                    attempt_generation != self._collector_generation
                    or self._collector_thread is not thread
                    or not _thread_is_alive(thread)
                ):
                    attempt_stop_event.set()
                    attempt_control.terminalize_unfinished("collector_attempt_superseded")
                    return {"ok": False, "error": "collector_attempt_superseded"}
                self._collector_ready_generation = attempt_generation
                database_maintenance_service.register_runtime_control(self)
                return {"ok": True, "started": True, "already_running": False}

        collector_health.record_health_code("collector_startup_not_ready")
        attempt_stop_event.set()
        thread.join(timeout=2)
        still_alive = _thread_is_alive(thread)
        if still_alive:
            attempt_control.terminalize_unfinished("collector_startup_stop_timeout")
        with self._lifecycle_lock:
            if attempt_generation == self._collector_generation:
                if still_alive:
                    self.phase = RuntimePhase.FAILED
                    return {"ok": False, "error": "collector_stop_timeout"}
                self._collector_thread = None
                self._collector_stop_event = None
                self.collector_control = RuntimeCollectorControl()
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
        return {"ok": False, "error": "collector_start_failed"}

    def is_collection_running_for_maintenance(self) -> bool:
        with self._lifecycle_lock:
            return bool(
                self.owns_application_instance
                and not self._shutdown
                and _thread_is_alive(self._collector_thread)
                and self._collector_stop_event is not None
                and not self._collector_stop_event.is_set()
            )

    def pause_collection_now(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        if not self.is_collection_running_for_maintenance():
            return {
                "ok": True,
                "pause_pending": False,
                "collector_active": False,
            }
        result = dict(self.collector_control.request_pause(timeout_seconds=timeout_seconds))
        result["collector_active"] = True
        return result

    def quiesce_collection_for_maintenance(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        if not self.is_collection_running_for_maintenance():
            return {
                "ok": True,
                "collector_active": False,
                "command_id": "inactive-collector",
                "command_kind": "maintenance_hold",
                "command_state": "completed",
                "command_state_unknown": False,
                "terminal_state": "held",
            }
        result = dict(
            self.collector_control.request_maintenance_hold(
                timeout_seconds=timeout_seconds
            )
        )
        result["collector_active"] = True
        return result

    def reset_after_database_replacement(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        if not self.is_collection_running_for_maintenance():
            self._adapter.reset_runtime_state()
            return {
                "ok": True,
                "collector_active": False,
                "command_id": "inactive-collector",
                "command_kind": "database_reset",
                "command_state": "completed",
                "command_state_unknown": False,
                "terminal_state": "held",
            }
        result = dict(
            self.collector_control.request_reset(timeout_seconds=timeout_seconds)
        )
        if bool(result.get("ok")):
            self._adapter.reset_runtime_state()
        result["collector_active"] = True
        return result

    def restore_after_maintenance(
        self,
        state: database_maintenance_service.RuntimeMaintenanceState,
        *,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        if self.is_collection_running_for_maintenance():
            result = dict(
                self.collector_control.request_maintenance_release(
                    timeout_seconds=timeout_seconds
                )
            )
            result["collector_active"] = True
            return result
        should_run = bool(
            state.collector_running
            and state.privacy_notice_accepted
            and not state.user_paused
        )
        if not should_run:
            return {
                "ok": True,
                "collector_active": False,
                "command_id": "inactive-collector",
                "command_kind": "maintenance_release",
                "command_state": "completed",
                "command_state_unknown": False,
                "terminal_state": "operational",
            }
        result = dict(self.start_collector(startup_timeout_seconds=timeout_seconds))
        if bool(result.get("ok")):
            result.update(
                {
                    "command_id": "collector-restarted",
                    "command_kind": "maintenance_release",
                    "command_state": "completed",
                    "command_state_unknown": False,
                    "terminal_state": "operational",
                }
            )
        return result

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool:
        self._adapter.set_clipboard_capture_enabled(bool(enabled))
        return True

    def request_shutdown(self) -> None:
        self.phase = RuntimePhase.STOPPING
        self.stop_event.set()
        if self._collector_stop_event is not None:
            self._collector_stop_event.set()
        folder_index_service.wake_folder_index_worker()
        for handle in self._worker_handles.values():
            handle.stop_event.set()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._shutdown:
                return
            self._shutdown = True
            self.phase = RuntimePhase.STOPPING
            database_maintenance_service.clear_runtime_control(self)
            self.stop_event.set()
            collector_thread = self._collector_thread
            collector_control = self.collector_control
            if self._collector_stop_event is not None:
                self._collector_stop_event.set()

        if collector_thread is not None:
            collector_thread.join(timeout=5)
            if _thread_is_alive(collector_thread):
                collector_control.terminalize_unfinished("collector_shutdown_timeout")

        with self._lifecycle_lock:
            handles = list(self._worker_handles.values())
            folder_index_service.wake_folder_index_worker()
            for handle in handles:
                handle.stop_event.set()

        for handle in handles:
            if handle.thread is not None:
                handle.thread.join(timeout=5)

        self._adapter.shutdown()

        surviving_workers = [
            handle for handle in handles if _thread_is_alive(handle.thread)
        ]
        collector_alive = _thread_is_alive(collector_thread)
        writers_stopped = not collector_alive and not surviving_workers

        with self._lifecycle_lock:
            self._worker_handles = {
                handle.spec.name: handle for handle in surviving_workers
            }
            if self.owns_application_instance and writers_stopped:
                if (
                    self._initialized
                    and not database_maintenance_service.MAINTENANCE_COORDINATOR.recovery_blocked()
                ):
                    shutdown_at = db.now_str()
                    activity_lifecycle_service.close_all_open_activities()
                    set_setting("collector_status", "stopped")
                    set_setting("last_shutdown_at", shutdown_at)
                release_single_instance()
                self.owns_application_instance = False
                self.phase = RuntimePhase.STOPPED
            elif self.owns_application_instance:
                self.phase = RuntimePhase.FAILED
                collector_health.record_health_code("shutdown_writer_still_alive")
                logging.error(
                    "app shutdown retained instance lock collector_alive=%s workers=%s",
                    collector_alive,
                    [handle.spec.name for handle in surviving_workers],
                )
            else:
                self.phase = RuntimePhase.STOPPED

        logging.info("app shutdown writers_stopped=%s", writers_stopped)


__all__ = [
    "AppRuntime",
    "RuntimePhase",
    "WorkerHandle",
    "WorkerSpec",
    "WorkerStartupReport",
    "WorkerStartupReporter",
]
