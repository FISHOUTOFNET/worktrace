"""Process-level application runtime.

Owns every long-lived runtime component: application instance lease, collector,
folder-index, history and inference workers, platform adapter, maintenance
command channels, and startup recovery. A process without the application lease
never opens the business database or creates the WebView.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import sys
import threading
import time
from typing import TYPE_CHECKING, Any

from .. import db
from ..collector import collector_health
from ..collector.collector import CollectorControl, run_collector
from ..collector.single_instance import acquire_single_instance, release_single_instance
from ..services import (
    activity_inference_job_service,
    activity_lifecycle_service,
    folder_index_service,
    history_mutation_job_service,
    project_inference_service,
    recovery_service,
)
from ..services.runtime_snapshot_barrier import (
    clear_quiesce_handler,
    register_quiesce_handler,
)
from ..services.secure_backup_service import (
    clear_collector_pause_handler,
    clear_collector_reset_handler,
    register_collector_pause_handler,
    register_collector_reset_handler,
)
from ..services.runtime_activity_state_service import clear_runtime_activity_state
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
    """Structured readiness for derived-state workers."""

    index_ready: bool
    history_ready: bool
    index_started: bool = False
    history_started: bool = False
    error: str | None = None
    inference_ready: bool = field(default=True, compare=False, repr=False)
    inference_started: bool = field(default=False, compare=False, repr=False)

    @property
    def ready(self) -> bool:
        return bool(self.index_ready and self.history_ready and self.inference_ready)

    @property
    def started_any(self) -> bool:
        return bool(
            self.index_started or self.history_started or self.inference_started
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "index_ready": self.index_ready,
            "history_ready": self.history_ready,
            "index_started": self.index_started,
            "history_started": self.history_started,
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

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "collector_ready": self.collector_ready,
            "folder_index_ready": self.folder_index_ready,
            "history_worker_ready": self.history_worker_ready,
            "already_running": self.already_running,
            "degraded": self.degraded,
            "background_worker_degraded": self.degraded,
        }
        if self.error_code:
            result["error"] = self.error_code
            result["error_code"] = self.error_code
        return result


def _choose_adapter():
    if sys.platform.startswith("win"):
        from ..platforms.windows_adapter import WindowsAdapter

        return WindowsAdapter()
    from ..platforms.fake_adapter import FakeAdapter

    return FakeAdapter()


def _thread_reference_is_alive(thread: Any | None) -> bool:
    if thread is None:
        return False
    checker = getattr(thread, "is_alive", None)
    return bool(checker()) if checker is not None else False


class AppRuntime:
    """Single owner for application, worker and adapter lifecycle."""

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
        self._registered_collector_thread_id: int | None = None
        self._initialized = False
        self._shutdown = False

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
            except Exception:
                release_single_instance()
                self.owns_application_instance = False
                self.phase = RuntimePhase.FAILED
                raise
            self._initialized = True
            self.phase = RuntimePhase.INITIALIZED
            return True

    def start_background_workers(self) -> WorkerReadiness:
        """Initialize, then start or confirm all derived-state workers."""

        with self._lifecycle_lock:
            if not self._initialized or not self.owns_application_instance:
                return WorkerReadiness(False, False, error="runtime_not_owned")
            if self._shutdown or self.stop_event.is_set():
                return WorkerReadiness(False, False, error="runtime_stopping")

            index_ready = _thread_reference_is_alive(self._index_thread)
            index_started = False
            if not index_ready:
                try:
                    folder_index_service.recover_interrupted_indexes()
                    folder_index_service.ensure_index_states_for_folder_rules()
                    folder_index_service.validate_ready_indexes(self.stop_event)
                    self._index_thread = (
                        folder_index_service.start_folder_index_worker(
                            self.stop_event
                        )
                    )
                    index_ready = _thread_reference_is_alive(self._index_thread)
                    index_started = index_ready
                except Exception:
                    self._index_thread = None
                    logging.exception("folder index worker initialization failed")

            history_ready = _thread_reference_is_alive(self._history_thread)
            history_started = False
            if not history_ready:
                try:
                    history_mutation_job_service.run_pending_jobs(limit=0)
                    self._history_thread = (
                        history_mutation_job_service.start_history_worker(
                            self.stop_event
                        )
                    )
                    history_ready = _thread_reference_is_alive(self._history_thread)
                    history_started = history_ready
                except Exception:
                    self._history_thread = None
                    logging.exception("history worker initialization failed")

            inference_ready = _thread_reference_is_alive(self._inference_thread)
            inference_started = False
            if not inference_ready:
                try:
                    self._inference_thread = (
                        activity_inference_job_service.start_inference_worker(
                            self.stop_event,
                            project_inference_service.assign_project_for_activity_in_transaction,
                        )
                    )
                    inference_ready = _thread_reference_is_alive(
                        self._inference_thread
                    )
                    inference_started = inference_ready
                except Exception:
                    self._inference_thread = None
                    logging.exception("inference worker initialization failed")

            all_ready = bool(index_ready and history_ready and inference_ready)
            error = None if all_ready else "worker_start_failed"
            return WorkerReadiness(
                index_ready=index_ready,
                history_ready=history_ready,
                index_started=index_started,
                history_started=history_started,
                error=error,
                inference_ready=inference_ready,
                inference_started=inference_started,
            )

    def start_authorized_collection(self) -> RuntimeStartResult:
        """Start the critical Collector before optional derived-state workers."""

        with self._lifecycle_lock:
            if not self._initialized or not self.owns_application_instance:
                return RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    folder_index_ready=False,
                    history_worker_ready=False,
                    degraded=True,
                    error_code="runtime_not_owned",
                )
            if self._shutdown or self.stop_event.is_set():
                return RuntimeStartResult(
                    ok=False,
                    collector_ready=False,
                    folder_index_ready=False,
                    history_worker_ready=False,
                    degraded=True,
                    error_code="runtime_stopping",
                )
            self.phase = RuntimePhase.STARTING

        retry_degraded = False
        try:
            project_inference_service.retry_pending_inference(1)
        except Exception:
            retry_degraded = True
            logging.exception("bounded pending inference convergence failed")

        try:
            collector_result = self.start_collector()
        except Exception:
            logging.exception("collector startup failed")
            collector_result = {
                "ok": False,
                "error": "collector_start_failed",
            }

        if not bool(collector_result.get("ok")):
            error_code = str(collector_result.get("error") or "collector_start_failed")
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
            )

        try:
            workers = self.start_background_workers()
        except Exception:
            logging.exception("background worker startup failed")
            workers = WorkerReadiness(
                index_ready=False,
                history_ready=False,
                error="worker_start_failed",
                inference_ready=False,
            )

        degraded = bool(retry_degraded or not workers.ready)
        self.phase = RuntimePhase.DEGRADED if degraded else RuntimePhase.RUNNING
        return RuntimeStartResult(
            ok=True,
            collector_ready=True,
            folder_index_ready=workers.index_ready,
            history_worker_ready=workers.history_ready,
            already_running=bool(collector_result.get("already_running")),
            degraded=degraded,
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
                if self._collector_stop_event is not None and self._collector_stop_event.is_set():
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
        register_collector_pause_handler(self.quiesce_collection_now)
        register_collector_reset_handler(self.reset_collection_runtime_now)
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
        return self.collector_control.request_pause(
            timeout_seconds=timeout_seconds
        )

    def quiesce_collection_now(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        prior_user_paused = get_bool_setting("user_paused", False)
        prior_collector_status = (
            get_setting("collector_status", "stopped") or "stopped"
        )
        result = self.pause_collection_now(timeout_seconds=timeout_seconds)
        if bool(result.get("ok")):
            set_setting(
                "user_paused",
                "true" if prior_user_paused else "false",
            )
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
        collector_stop_event = self._collector_stop_event
        if collector_stop_event is not None:
            collector_stop_event.set()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._shutdown:
                return
            self._shutdown = True
            self.phase = RuntimePhase.STOPPING
            clear_collector_pause_handler(self.quiesce_collection_now)
            clear_collector_reset_handler(self.reset_collection_runtime_now)
            clear_quiesce_handler(self.quiesce_collection_now)
            self.set_clipboard_capture_enabled(False)
            self.stop_event.set()
            folder_index_service.wake_folder_index_worker()
            if self._collector_stop_event is not None:
                self._collector_stop_event.set()
            workers = [
                self._index_thread,
                self._history_thread,
                self._inference_thread,
                self._collector_thread,
            ]

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

        for thread in (
            self._index_thread,
            self._history_thread,
            self._inference_thread,
        ):
            if thread:
                joiner = getattr(thread, "join", None)
                if joiner is not None:
                    joiner(timeout=5)

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
