"""Process-level owner for the complete WorkTrace application runtime."""
from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from .. import db
from ..collector import collector_health
from ..collector.collector import CollectorControl, run_collector
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
from ..services.runtime_activity_state_service import clear_runtime_activity_state
from ..services.runtime_snapshot_barrier import (
    clear_quiesce_handler,
    register_quiesce_handler,
)
from ..services.settings_service import get_bool_setting, get_setting, set_setting
from ..write_gate import DATABASE_WRITE_GATE

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


@dataclass(frozen=True)
class WorkerReadiness:
    """Readiness of every non-critical AppRuntime-owned worker."""

    index_ready: bool
    history_ready: bool
    index_started: bool = False
    history_started: bool = False
    error: str | None = None
    inference_ready: bool = True
    inference_started: bool = False
    resource_repair_ready: bool = True
    resource_repair_started: bool = False
    startup_recovery_ready: bool = True
    startup_recovery_started: bool = False
    failed_workers: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return bool(
            self.index_ready
            and self.history_ready
            and self.inference_ready
            and self.resource_repair_ready
            and self.startup_recovery_ready
        )

    @property
    def started_any(self) -> bool:
        return bool(
            self.index_started
            or self.history_started
            or self.inference_started
            or self.resource_repair_started
            or self.startup_recovery_started
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "index_ready": self.index_ready,
            "history_ready": self.history_ready,
            "inference_ready": self.inference_ready,
            "resource_repair_ready": self.resource_repair_ready,
            "startup_recovery_ready": self.startup_recovery_ready,
            "index_started": self.index_started,
            "history_started": self.history_started,
            "inference_started": self.inference_started,
            "resource_repair_started": self.resource_repair_started,
            "startup_recovery_started": self.startup_recovery_started,
            "failed_workers": list(self.failed_workers),
            "error": self.error,
        }


@dataclass(frozen=True)
class RuntimeStartResult:
    """Complete result of the authorized startup sequence."""

    ok: bool
    collector_ready: bool
    folder_index_ready: bool
    history_worker_ready: bool
    already_running: bool = False
    degraded: bool = False
    error_code: str | None = None
    inference_worker_ready: bool = True
    resource_repair_worker_ready: bool = True
    startup_recovery_worker_ready: bool = True
    failed_workers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "collector_ready": self.collector_ready,
            "folder_index_ready": self.folder_index_ready,
            "history_worker_ready": self.history_worker_ready,
            "inference_worker_ready": self.inference_worker_ready,
            "resource_repair_worker_ready": self.resource_repair_worker_ready,
            "startup_recovery_worker_ready": self.startup_recovery_worker_ready,
            "already_running": self.already_running,
            "degraded": self.degraded,
            "background_worker_degraded": self.degraded,
            "failed_workers": list(self.failed_workers),
        }
        if self.error_code:
            result["error"] = self.error_code
            result["error_code"] = self.error_code
        return result


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
        self.collector_control = CollectorControl()
        self.phase = RuntimePhase.NEW
        self._lifecycle_lock = threading.RLock()
        self._adapter = adapter if adapter is not None else _choose_adapter()
        self._collector_thread: threading.Thread | None = None
        self._collector_stop_event: threading.Event | None = None
        self._collector_generation = 0
        self._index_thread: threading.Thread | None = None
        self._history_thread: threading.Thread | None = None
        self._inference_thread: threading.Thread | None = None
        self._resource_repair_thread: threading.Thread | None = None
        self._startup_recovery_thread: threading.Thread | None = None
        self._registered_collector_thread_id: int | None = None
        self._initialized = False
        self._shutdown = False

    def initialize(self) -> bool:
        """Acquire the application lease and perform bounded startup recovery."""

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
            except Exception:
                release_single_instance()
                self.owns_application_instance = False
                self.phase = RuntimePhase.FAILED
                raise
            self._initialized = True
            self.phase = RuntimePhase.INITIALIZED
            return True

    def _start_owned_worker(
        self,
        *,
        reference_name: str,
        worker_name: str,
        target: Callable[..., None],
        args: tuple[Any, ...] = (),
    ) -> tuple[bool, bool]:
        """Start one blocking worker target and retain its only thread reference."""

        current = getattr(self, reference_name)
        if _thread_reference_is_alive(current):
            return True, False
        if current is not None:
            setattr(self, reference_name, None)
        thread = threading.Thread(
            target=target,
            args=args,
            name=worker_name,
            daemon=True,
        )
        setattr(self, reference_name, thread)
        try:
            thread.start()
        except Exception:
            setattr(self, reference_name, None)
            raise
        ready = _thread_reference_is_alive(thread)
        if not ready:
            setattr(self, reference_name, None)
        return ready, ready

    def _clear_dead_worker_references(self) -> None:
        for reference_name in (
            "_index_thread",
            "_history_thread",
            "_inference_thread",
            "_resource_repair_thread",
            "_startup_recovery_thread",
        ):
            thread = getattr(self, reference_name)
            if thread is not None and not _thread_reference_is_alive(thread):
                setattr(self, reference_name, None)

    def start_background_workers(self) -> WorkerReadiness:
        """Start each bounded non-critical worker at most once."""

        with self._lifecycle_lock:
            all_worker_names = (
                "folder_index",
                "history",
                "inference",
                "activity_resource_repair",
                "startup_recovery",
            )
            if not self._initialized or not self.owns_application_instance:
                return WorkerReadiness(
                    False,
                    False,
                    error="runtime_not_owned",
                    inference_ready=False,
                    resource_repair_ready=False,
                    startup_recovery_ready=False,
                    failed_workers=all_worker_names,
                )
            if self._shutdown or self.stop_event.is_set():
                return WorkerReadiness(
                    False,
                    False,
                    error="runtime_stopping",
                    inference_ready=False,
                    resource_repair_ready=False,
                    startup_recovery_ready=False,
                    failed_workers=all_worker_names,
                )

            self._clear_dead_worker_references()

            index_ready, index_started = self._start_worker_safely(
                reference_name="_index_thread",
                worker_name="WorkTraceFolderIndex",
                target=folder_index_service.run_folder_index_worker,
                failure_log="folder index worker initialization failed",
            )
            history_ready, history_started = self._start_worker_safely(
                reference_name="_history_thread",
                worker_name="WorkTraceHistoryMutation",
                target=history_mutation_job_service.run_history_worker,
                failure_log="history worker initialization failed",
            )
            inference_ready, inference_started = self._start_worker_safely(
                reference_name="_inference_thread",
                worker_name="WorkTraceInferenceWorker",
                target=activity_inference_job_service.run_inference_worker,
                args=(
                    self.stop_event,
                    project_inference_service.assign_project_for_activity_in_transaction,
                ),
                include_stop_event=False,
                failure_log="inference worker initialization failed",
            )
            resource_repair_ready, resource_repair_started = self._start_worker_safely(
                reference_name="_resource_repair_thread",
                worker_name="WorkTraceActivityResourceRepair",
                target=activity_fact_repair_service.run_activity_resource_repair_worker,
                failure_log="activity resource repair worker initialization failed",
            )
            startup_recovery_ready, startup_recovery_started = self._start_worker_safely(
                reference_name="_startup_recovery_thread",
                worker_name="WorkTraceStartupRecovery",
                target=recovery_service.run_startup_recovery_worker,
                failure_log="startup recovery worker initialization failed",
            )

            failed_workers = tuple(
                name
                for name, ready in (
                    ("folder_index", index_ready),
                    ("history", history_ready),
                    ("inference", inference_ready),
                    ("activity_resource_repair", resource_repair_ready),
                    ("startup_recovery", startup_recovery_ready),
                )
                if not ready
            )
            return WorkerReadiness(
                index_ready=index_ready,
                history_ready=history_ready,
                index_started=index_started,
                history_started=history_started,
                error="worker_start_failed" if failed_workers else None,
                inference_ready=inference_ready,
                inference_started=inference_started,
                resource_repair_ready=resource_repair_ready,
                resource_repair_started=resource_repair_started,
                startup_recovery_ready=startup_recovery_ready,
                startup_recovery_started=startup_recovery_started,
                failed_workers=failed_workers,
            )

    def _start_worker_safely(
        self,
        *,
        reference_name: str,
        worker_name: str,
        target: Callable[..., None],
        failure_log: str,
        args: tuple[Any, ...] = (),
        include_stop_event: bool = True,
    ) -> tuple[bool, bool]:
        try:
            worker_args = (self.stop_event, *args) if include_stop_event else args
            return self._start_owned_worker(
                reference_name=reference_name,
                worker_name=worker_name,
                target=target,
                args=worker_args,
            )
        except Exception:
            setattr(self, reference_name, None)
            logging.exception(failure_log)
            return False, False

    def start_authorized_collection(self) -> RuntimeStartResult:
        """Start critical Collector first, then non-critical workers."""

        with self._lifecycle_lock:
            if not self._initialized or not self.owns_application_instance:
                return RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    folder_index_ready=False,
                    history_worker_ready=False,
                    degraded=True,
                    error_code="runtime_not_owned",
                    inference_worker_ready=False,
                    resource_repair_worker_ready=False,
                    startup_recovery_worker_ready=False,
                )
            if self._shutdown or self.stop_event.is_set():
                return RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    folder_index_ready=False,
                    history_worker_ready=False,
                    degraded=True,
                    error_code="runtime_stopping",
                    inference_worker_ready=False,
                    resource_repair_worker_ready=False,
                    startup_recovery_worker_ready=False,
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
                folder_index_ready=False,
                history_worker_ready=False,
                degraded=True,
                error_code=error_code,
                inference_worker_ready=False,
                resource_repair_worker_ready=False,
                startup_recovery_worker_ready=False,
            )

        try:
            workers = self.start_background_workers()
        except Exception:
            logging.exception("background worker startup failed")
            workers = WorkerReadiness(
                False,
                False,
                error="worker_start_failed",
                inference_ready=False,
                resource_repair_ready=False,
                startup_recovery_ready=False,
                failed_workers=(
                    "folder_index",
                    "history",
                    "inference",
                    "activity_resource_repair",
                    "startup_recovery",
                ),
            )

        degraded = not workers.ready
        self.phase = RuntimePhase.DEGRADED if degraded else RuntimePhase.RUNNING
        return RuntimeStartResult(
            ok=True,
            collector_ready=True,
            folder_index_ready=workers.index_ready,
            history_worker_ready=workers.history_ready,
            inference_worker_ready=workers.inference_ready,
            resource_repair_worker_ready=workers.resource_repair_ready,
            startup_recovery_worker_ready=workers.startup_recovery_ready,
            already_running=bool(collector_result.get("already_running")),
            degraded=degraded,
            failed_workers=workers.failed_workers,
        )

    def _register_collector_write_thread(self) -> None:
        thread_id = getattr(self._collector_thread, "ident", None)
        if thread_id is None:
            return
        normalized = int(thread_id)
        if self._registered_collector_thread_id == normalized:
            return
        self._clear_collector_write_thread()
        DATABASE_WRITE_GATE.register_maintenance_thread(normalized)
        self._registered_collector_thread_id = normalized

    def _clear_collector_write_thread(self) -> None:
        thread_id = self._registered_collector_thread_id
        if thread_id is None:
            return
        DATABASE_WRITE_GATE.unregister_maintenance_thread(thread_id)
        self._registered_collector_thread_id = None

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
                self._register_collector_write_thread()
                self._register_maintenance_handlers()
                return {"ok": True, "started": False, "already_running": True}
            if self._collector_thread is not None:
                collector_health.record_health_code("thread_dead_replaced")
                self._clear_collector_write_thread()
                self._collector_thread = None
                self._collector_stop_event = None

            ready_event = threading.Event()
            failed_event = threading.Event()
            attempt_stop_event = threading.Event()
            attempt_control = CollectorControl()
            self._collector_generation += 1
            attempt_generation = self._collector_generation
            self._collector_stop_event = attempt_stop_event
            self.collector_control = attempt_control
            try:
                thread = threading.Thread(
                    target=run_collector,
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
                self._clear_collector_write_thread()
                self._collector_thread = None
                self._collector_stop_event = None
                self.collector_control = CollectorControl()
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
                    return {"ok": False, "error": "collector_attempt_superseded"}
                self._register_collector_write_thread()
                self._register_maintenance_handlers()
                return {"ok": True, "started": True, "already_running": False}

        collector_health.record_health_code("collector_startup_not_ready")
        attempt_stop_event.set()
        joiner = getattr(thread, "join", None)
        if joiner is not None:
            joiner(timeout=2)
        still_alive = _thread_reference_is_alive(thread)
        with self._lifecycle_lock:
            if attempt_generation == self._collector_generation:
                self._clear_collector_write_thread()
                if still_alive:
                    self.phase = RuntimePhase.FAILED
                    return {"ok": False, "error": "collector_stop_timeout"}
                self._collector_thread = None
                self._collector_stop_event = None
                self.collector_control = CollectorControl()
                self.phase = RuntimePhase.RECOVERABLE_FAILURE
        return {"ok": False, "error": "collector_start_failed"}

    def _register_maintenance_handlers(self) -> None:
        database_maintenance_service.register_collector_pause_handler(
            self.quiesce_collection_now
        )
        database_maintenance_service.register_collector_reset_handler(
            self.reset_collection_runtime_now
        )
        register_quiesce_handler(self.quiesce_collection_now)

    def pause_collection_now(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        if not self.owns_application_instance or not _thread_reference_is_alive(
            self._collector_thread
        ):
            return {
                "ok": True,
                "pause_pending": False,
                "collector_active": False,
            }
        return self.collector_control.request_pause(timeout_seconds=timeout_seconds)

    def quiesce_collection_now(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        prior_user_paused = get_bool_setting("user_paused", False)
        prior_collector_status = get_setting("collector_status", "stopped") or "stopped"
        result = self.pause_collection_now(timeout_seconds=timeout_seconds)
        if bool(result.get("ok")):
            set_setting("user_paused", "true" if prior_user_paused else "false")
            set_setting("collector_status", prior_collector_status)
        elif bool(result.get("command_state_unknown")):
            set_setting("user_paused", "true")
            set_setting("collector_status", "paused")
            clear_runtime_activity_state("collector_pause_state_unknown")
        return result

    def reset_collection_runtime_now(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        if not self.owns_application_instance or not _thread_reference_is_alive(
            self._collector_thread
        ):
            self._reset_adapter_runtime_state()
            return {
                "ok": True,
                "reset_pending": False,
                "collector_active": False,
            }
        result = self.collector_control.request_reset(
            timeout_seconds=timeout_seconds
        )
        if bool(result.get("ok")):
            self._reset_adapter_runtime_state()
        elif bool(result.get("command_state_unknown")):
            set_setting("user_paused", "true")
            set_setting("collector_status", "paused")
            clear_runtime_activity_state("collector_reset_state_unknown")
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
        if self._collector_stop_event is not None:
            self._collector_stop_event.set()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._shutdown:
                return
            self._shutdown = True
            self.phase = RuntimePhase.STOPPING
            database_maintenance_service.clear_collector_pause_handler(
                self.quiesce_collection_now
            )
            database_maintenance_service.clear_collector_reset_handler(
                self.reset_collection_runtime_now
            )
            clear_quiesce_handler(self.quiesce_collection_now)
            self.set_clipboard_capture_enabled(False)
            self.stop_event.set()
            folder_index_service.wake_folder_index_worker()
            if self._collector_stop_event is not None:
                self._collector_stop_event.set()
            derived_workers = (
                self._index_thread,
                self._history_thread,
                self._inference_thread,
                self._resource_repair_thread,
                self._startup_recovery_thread,
            )
            workers = (*derived_workers, self._collector_thread)

        adapter_shutdown = False
        collector_thread = self._collector_thread
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

        if not _thread_reference_is_alive(self._collector_thread):
            self._clear_collector_write_thread()

        for thread in derived_workers:
            if thread:
                joiner = getattr(thread, "join", None)
                if joiner is not None:
                    joiner(timeout=5)

        with self._lifecycle_lock:
            self._clear_dead_worker_references()

        writers_stopped = not any(
            _thread_reference_is_alive(thread) for thread in workers
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
    "WorkerReadiness",
]
