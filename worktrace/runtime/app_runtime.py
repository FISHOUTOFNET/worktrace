"""Process-level owner for the complete WorkTrace application runtime."""
from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from .. import db
from ..collector import collector_health
from ..collector.collector import run_collector
from ..collector.runtime_control import RuntimeCollectorControl
from ..collector.single_instance import acquire_single_instance, release_single_instance
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
)
from ..services.settings_service import set_setting
from ..worker_health import WorkerHealthRegistry, WorkerHealthReporter

if TYPE_CHECKING:
    class _Paths:
        db_path: str
        log_path: str

    _Paths = _Paths  # noqa: F811


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
            "ready": bool(self.ready),
            "started": bool(self.started),
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    thread_name: str
    target: Callable[..., None]
    args_factory: Callable[[threading.Event], tuple[Any, ...]]
    startup_timeout_seconds: float = 5.0
    critical: bool = False


@dataclass
class WorkerHandle:
    spec: WorkerSpec
    thread: threading.Thread | None
    stop_event: threading.Event
    ready_event: threading.Event = field(default_factory=threading.Event)
    failed_event: threading.Event = field(default_factory=threading.Event)
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
            if self._handle.failed_event.is_set():
                return
            self._handle.ready_event.set()

    def failed(self, code: str) -> None:
        with self._lock:
            if self._handle.ready_event.is_set():
                return
            self._handle.error_code = str(code or "worker_startup_failed")
            self._handle.failed_event.set()


class _OwnedWorkerReporter:
    """Worker-facing health capability carrying the startup handshake."""

    def __init__(
        self,
        health: WorkerHealthReporter,
        startup: WorkerStartupReporter,
    ) -> None:
        self._health = health
        self._startup = startup
        self.name = health.name

    def succeeded(self) -> None:
        self._startup.ready()
        self._health.succeeded()

    def failed(self, code: str) -> None:
        self._startup.failed(code)
        self._health.failed(code)

    def maintenance_paused(self, paused: bool) -> None:
        self._health.maintenance_paused(paused)


@dataclass(frozen=True)
class WorkerStartupReport:
    workers: dict[str, WorkerStartupStatus]
    error_code: str | None = None

    @property
    def ready(self) -> bool:
        return all(status.ready for status in self.workers.values())

    @property
    def started_any(self) -> bool:
        return any(status.started for status in self.workers.values())

    @property
    def failed_workers(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, status in self.workers.items()
            if not status.ready
        )


@dataclass(frozen=True)
class RuntimeStartResult:
    """Complete result of the authorized startup sequence."""

    ok: bool
    collector_ready: bool
    workers: dict[str, WorkerStartupStatus]
    already_running: bool = False
    degraded: bool = False
    error_code: str | None = None

    @property
    def failed_workers(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, status in self.workers.items()
            if not status.ready
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": bool(self.ok),
            "collector_ready": bool(self.collector_ready),
            "workers": {
                name: status.to_dict()
                for name, status in sorted(self.workers.items())
            },
            "already_running": bool(self.already_running),
            "degraded": bool(self.degraded),
            "error_code": self.error_code,
        }


def _choose_adapter() -> WindowsAdapter:
    if not sys.platform.startswith("win"):
        raise RuntimeError("unsupported_platform")
    return WindowsAdapter()


def _thread_reference_is_alive(thread: Any | None) -> bool:
    if thread is None:
        return False
    checker = getattr(thread, "is_alive", None)
    return bool(checker()) if checker is not None else False


class AppRuntime:
    """Single owner for instance, adapter, Collector and worker lifecycles."""

    def __init__(self, paths: "_Paths", adapter: Any | None = None) -> None:
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
        self._worker_handles: dict[str, WorkerHandle] = {}
        self._worker_specs = self._build_worker_specs()
        self._initialized = False
        self._shutdown = False

    def _build_worker_specs(self) -> dict[str, WorkerSpec]:
        return {
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
                logging.warning(
                    "single application instance lock not acquired; startup aborted"
                )
                return False
            try:
                db.initialize_database(self.paths.db_path)
                recovery_service.recover_unclosed_records()
                database_maintenance_service.register_runtime_control(self)
            except Exception:
                database_maintenance_service.clear_runtime_control(self)
                release_single_instance()
                self.owns_application_instance = False
                self.phase = RuntimePhase.FAILED
                raise
            self._initialized = True
            self.phase = RuntimePhase.INITIALIZED
            return True

    def _run_owned_worker(self, handle: WorkerHandle) -> None:
        spec = handle.spec
        health = self._worker_health.reporter(spec.name)
        startup = WorkerStartupReporter(handle)
        worker_reporter = _OwnedWorkerReporter(health, startup)
        health.started()
        try:
            spec.target(
                *spec.args_factory(handle.stop_event),
                health=worker_reporter,
            )
            if not startup.ready_reported and not startup.failed_reported:
                startup.failed("worker_returned_before_ready")
            if not handle.stop_event.is_set() and not self.stop_event.is_set():
                handle.error_code = "worker_unexpected_exit"
                handle.failed_event.set()
                health.failed(handle.error_code)
                logging.error(
                    "owned worker returned unexpectedly worker=%s",
                    spec.name,
                )
        except Exception:
            if not startup.ready_reported:
                startup.failed("worker_startup_failed")
            else:
                handle.error_code = "worker_unhandled_exception"
                handle.failed_event.set()
            health.failed(handle.error_code or "worker_unhandled_exception")
            logging.exception("owned worker failed worker=%s", spec.name)
        finally:
            health.stopped()
            if self.phase in {RuntimePhase.RUNNING, RuntimePhase.STARTING}:
                self.phase = RuntimePhase.DEGRADED

    @staticmethod
    def _run_owned_collector(
        adapter: Any,
        stop_event: threading.Event,
        control: RuntimeCollectorControl,
        ready_event: threading.Event,
        failed_event: threading.Event,
    ) -> None:
        try:
            run_collector(
                adapter,
                stop_event,
                control,
                ready_event,
                failed_event,
            )
        finally:
            reason = (
                "collector_fatal_exit"
                if failed_event.is_set() or not stop_event.is_set()
                else "collector_shutdown"
            )
            control.terminalize_unfinished(reason)

    def worker_health_snapshot(self) -> dict[str, object]:
        return {
            "workers": self._worker_health.public_snapshot(),
            "degraded_workers": list(self._worker_health.degraded_workers()),
        }

    def worker_registry_snapshot(self) -> dict[str, WorkerStartupStatus]:
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
    ) -> WorkerStartupStatus:
        alive = _thread_reference_is_alive(handle.thread)
        ready = bool(handle.ready_event.is_set() and alive)
        if ready:
            state = WorkerStartupState.READY
        elif handle.failed_event.is_set() or handle.error_code:
            state = WorkerStartupState.FAILED
        elif alive:
            state = WorkerStartupState.STARTING
        else:
            state = WorkerStartupState.STOPPED
        return WorkerStartupStatus(
            state=state,
            ready=ready,
            started=started,
            error_code=handle.error_code,
        )

    def _start_worker(self, spec: WorkerSpec) -> WorkerStartupStatus:
        existing = self._worker_handles.get(spec.name)
        if existing is not None and _thread_reference_is_alive(existing.thread):
            return self._await_worker_startup(existing, started=False)
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
            return WorkerStartupStatus(
                WorkerStartupState.FAILED,
                False,
                started=False,
                error_code=handle.error_code,
            )
        return self._await_worker_startup(handle, started=True)

    def _await_worker_startup(
        self,
        handle: WorkerHandle,
        *,
        started: bool,
    ) -> WorkerStartupStatus:
        deadline = time.monotonic() + max(
            0.1,
            float(handle.spec.startup_timeout_seconds),
        )
        while time.monotonic() < deadline:
            if handle.ready_event.wait(timeout=0.05):
                return self._status_for_handle(handle, started=started)
            if (
                handle.failed_event.is_set()
                or not _thread_reference_is_alive(handle.thread)
            ):
                return self._status_for_handle(handle, started=started)
        handle.error_code = "worker_startup_timeout"
        handle.failed_event.set()
        handle.stop_event.set()
        joiner = getattr(handle.thread, "join", None)
        if joiner is not None:
            joiner(timeout=1.0)
        if not _thread_reference_is_alive(handle.thread):
            self._worker_handles.pop(handle.spec.name, None)
        return WorkerStartupStatus(
            WorkerStartupState.FAILED,
            False,
            started=started,
            error_code=handle.error_code,
        )

    def start_background_workers(self) -> WorkerStartupReport:
        with self._lifecycle_lock:
            if not self._initialized or not self.owns_application_instance:
                statuses = {
                    name: WorkerStartupStatus(
                        WorkerStartupState.FAILED,
                        False,
                        error_code="runtime_not_owned",
                    )
                    for name in self._worker_specs
                }
                return WorkerStartupReport(statuses, "runtime_not_owned")
            if self._shutdown or self.stop_event.is_set():
                statuses = {
                    name: WorkerStartupStatus(
                        WorkerStartupState.STOPPED,
                        False,
                        error_code="runtime_stopping",
                    )
                    for name in self._worker_specs
                }
                return WorkerStartupReport(statuses, "runtime_stopping")

            statuses = {
                name: self._start_worker(spec)
                for name, spec in self._worker_specs.items()
            }
            error_code = (
                "worker_start_failed"
                if any(not status.ready for status in statuses.values())
                else None
            )
            return WorkerStartupReport(statuses, error_code)

    def start_authorized_collection(self) -> RuntimeStartResult:
        with self._lifecycle_lock:
            if not self._initialized or not self.owns_application_instance:
                return RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    workers={},
                    degraded=True,
                    error_code="runtime_not_owned",
                )
            if self._shutdown or self.stop_event.is_set():
                return RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    workers={},
                    degraded=True,
                    error_code="runtime_stopping",
                )
            self.phase = RuntimePhase.STARTING

        try:
            collector_result = self.start_collector()
        except Exception:
            logging.exception("collector startup failed")
            collector_result = {"ok": False, "error": "collector_start_failed"}

        if not bool(collector_result.get("ok")):
            error_code = str(
                collector_result.get("error") or "collector_start_failed"
            )
            self.phase = (
                RuntimePhase.FAILED
                if error_code in {"collector_stop_timeout", "runtime_stopping"}
                else RuntimePhase.RECOVERABLE_FAILURE
            )
            return RuntimeStartResult(
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
                    name: WorkerStartupStatus(
                        WorkerStartupState.FAILED,
                        False,
                        error_code="worker_start_failed",
                    )
                    for name in self._worker_specs
                },
                "worker_start_failed",
            )

        degraded = not report.ready
        self.phase = RuntimePhase.DEGRADED if degraded else RuntimePhase.RUNNING
        return RuntimeStartResult(
            ok=True,
            collector_ready=True,
            workers=report.workers,
            already_running=bool(collector_result.get("already_running")),
            degraded=degraded,
            error_code=report.error_code,
        )

    def start_collector(
        self,
        *,
        startup_timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        with self._lifecycle_lock:
            if self._shutdown or self.stop_event.is_set():
                return {"ok": False, "error": "runtime_stopping"}
            if not self.owns_application_instance:
                return {"ok": False, "error": "collector_not_owned"}
            if _thread_reference_is_alive(self._collector_thread):
                if (
                    self._collector_stop_event is not None
                    and self._collector_stop_event.is_set()
                ):
                    return {"ok": False, "error": "collector_stopping"}
                database_maintenance_service.register_runtime_control(self)
                return {"ok": True, "started": False, "already_running": True}
            if self._collector_thread is not None:
                collector_health.record_health_code("thread_dead_replaced")
                self._collector_thread = None
                self._collector_stop_event = None

            ready_event = threading.Event()
            failed_event = threading.Event()
            attempt_stop_event = threading.Event()
            attempt_control = RuntimeCollectorControl()
            self._collector_generation += 1
            attempt_generation = self._collector_generation
            self._collector_stop_event = attempt_stop_event
            self.collector_control = attempt_control
            try:
                thread = threading.Thread(
                    target=self._run_owned_collector,
                    args=(
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
            if failed_event.is_set() or not _thread_reference_is_alive(thread):
                break

        if startup_ready:
            with self._lifecycle_lock:
                if (
                    attempt_generation != self._collector_generation
                    or self._collector_thread is not thread
                ):
                    attempt_stop_event.set()
                    attempt_control.terminalize_unfinished(
                        "collector_attempt_superseded"
                    )
                    return {"ok": False, "error": "collector_attempt_superseded"}
                database_maintenance_service.register_runtime_control(self)
                return {"ok": True, "started": True, "already_running": False}

        collector_health.record_health_code("collector_startup_not_ready")
        attempt_stop_event.set()
        joiner = getattr(thread, "join", None)
        if joiner is not None:
            joiner(timeout=2)
        still_alive = _thread_reference_is_alive(thread)
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
                and _thread_reference_is_alive(self._collector_thread)
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
        result = dict(
            self.collector_control.request_pause(timeout_seconds=timeout_seconds)
        )
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

    def quiesce_collection_now(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        return self.quiesce_collection_for_maintenance(timeout_seconds)

    def reset_after_database_replacement(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        if not self.is_collection_running_for_maintenance():
            self._reset_adapter_runtime_state()
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
            self._reset_adapter_runtime_state()
        result["collector_active"] = True
        return result

    def reset_collection_runtime_now(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        return self.reset_after_database_replacement(timeout_seconds)

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
        result = dict(
            self.start_collector(startup_timeout_seconds=timeout_seconds)
        )
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

    def _reset_adapter_runtime_state(self) -> None:
        resetter = getattr(self._adapter, "reset_runtime_state", None)
        if resetter is not None:
            resetter()

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool:
        setter = getattr(self._adapter, "set_clipboard_capture_enabled", None)
        if setter is not None:
            setter(bool(enabled))
        return True

    def request_shutdown(self) -> None:
        self.phase = RuntimePhase.STOPPING
        self.stop_event.set()
        folder_index_service.wake_folder_index_worker()
        for handle in self._worker_handles.values():
            handle.stop_event.set()
        if self._collector_stop_event is not None:
            self._collector_stop_event.set()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._shutdown:
                return
            self._shutdown = True
            self.phase = RuntimePhase.STOPPING
            database_maintenance_service.clear_runtime_control(self)
            self.set_clipboard_capture_enabled(False)
            self.stop_event.set()
            folder_index_service.wake_folder_index_worker()
            handles = list(self._worker_handles.values())
            for handle in handles:
                handle.stop_event.set()
            if self._collector_stop_event is not None:
                self._collector_stop_event.set()
            collector_thread = self._collector_thread
            collector_control = self.collector_control

        adapter_shutdown = False
        if collector_thread:
            joiner = getattr(collector_thread, "join", None)
            if joiner is not None:
                joiner(timeout=5)
            if _thread_reference_is_alive(collector_thread):
                shutdown_adapter = getattr(self._adapter, "shutdown", None)
                if shutdown_adapter is not None:
                    shutdown_adapter()
                    adapter_shutdown = True
                if joiner is not None:
                    joiner(timeout=5)
            if _thread_reference_is_alive(collector_thread):
                collector_control.terminalize_unfinished(
                    "collector_shutdown_timeout"
                )

        for handle in handles:
            thread = handle.thread
            if thread is not None:
                joiner = getattr(thread, "join", None)
                if joiner is not None:
                    joiner(timeout=5)

        with self._lifecycle_lock:
            self._worker_handles = {
                name: handle
                for name, handle in self._worker_handles.items()
                if _thread_reference_is_alive(handle.thread)
            }

        writers = [collector_thread, *(handle.thread for handle in handles)]
        writers_stopped = not any(
            _thread_reference_is_alive(thread) for thread in writers
        )
        if self.owns_application_instance and writers_stopped:
            if self._initialized:
                activity_lifecycle_service.close_all_open_activities()
                set_setting("collector_status", "stopped")
            release_single_instance()
            self.owns_application_instance = False
            self.phase = RuntimePhase.STOPPED
        elif self.owns_application_instance:
            self.phase = RuntimePhase.FAILED
            collector_health.record_health_code("shutdown_writer_still_alive")
            logging.error("app shutdown retained instance lock: writer alive")
        else:
            self.phase = RuntimePhase.STOPPED

        if not adapter_shutdown:
            shutdown_adapter = getattr(self._adapter, "shutdown", None)
            if shutdown_adapter is not None:
                shutdown_adapter()
        logging.info("app shutdown writers_stopped=%s", writers_stopped)


__all__ = [
    "AppRuntime",
    "RuntimePhase",
    "RuntimeStartResult",
    "WorkerHandle",
    "WorkerSpec",
    "WorkerStartupReport",
    "WorkerStartupReporter",
    "WorkerStartupState",
    "WorkerStartupStatus",
]
