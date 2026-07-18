"""Process-level application runtime with explicit inference-worker ownership."""

from __future__ import annotations

import logging
from typing import Any

from ..platforms.windows_adapter import WindowsAdapter  # canonical production adapter
from ..services import activity_inference_job_service, project_inference_service
from . import app_runtime_core as _core
from .app_runtime_core import (
    AppRuntime as _CoreAppRuntime,
    RuntimePhase,
    RuntimeStartResult,
    WorkerReadiness,
    _thread_reference_is_alive,
)

# Keep the canonical module as the composition/test injection boundary while the
# stable implementation remains temporarily isolated for the staged cutover.
acquire_single_instance = _core.acquire_single_instance
release_single_instance = _core.release_single_instance
run_collector = _core.run_collector


def _synchronize_core_hooks() -> None:
    _core.acquire_single_instance = acquire_single_instance
    _core.release_single_instance = release_single_instance
    _core.run_collector = run_collector


class AppRuntime(_CoreAppRuntime):
    """Extend the stable runtime core with one durable-inference worker owner."""

    def __init__(self, paths: Any, adapter: Any | None = None) -> None:
        _synchronize_core_hooks()
        super().__init__(paths, adapter=adapter)
        self._inference_thread = None

    def initialize(self) -> bool:
        _synchronize_core_hooks()
        return super().initialize()

    def start_collector(
        self,
        *,
        startup_timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        _synchronize_core_hooks()
        return super().start_collector(
            startup_timeout_seconds=startup_timeout_seconds
        )

    def start_background_workers(self) -> WorkerReadiness:
        readiness = super().start_background_workers()
        with self._lifecycle_lock:
            inference_ready = _thread_reference_is_alive(self._inference_thread)
            if (
                not inference_ready
                and self._initialized
                and self.owns_application_instance
                and not self._shutdown
                and not self.stop_event.is_set()
            ):
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
                except Exception:
                    self._inference_thread = None
                    logging.exception("inference worker initialization failed")

        if inference_ready:
            return readiness
        return WorkerReadiness(
            index_ready=readiness.index_ready,
            history_ready=readiness.history_ready,
            index_started=readiness.index_started,
            history_started=readiness.history_started,
            error=readiness.error or "inference_worker_start_failed",
        )

    def start_authorized_collection(self) -> RuntimeStartResult:
        """Start Collector first, then all optional derived-state workers."""

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

        try:
            collector_result = self.start_collector()
        except Exception:
            logging.exception("collector startup failed")
            collector_result = {
                "ok": False,
                "error": "collector_start_failed",
            }

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
            )

        try:
            workers = self.start_background_workers()
        except Exception:
            logging.exception("background worker startup failed")
            workers = WorkerReadiness(
                index_ready=False,
                history_ready=False,
                error="worker_start_failed",
            )

        inference_ready = _thread_reference_is_alive(self._inference_thread)
        degraded = bool(not workers.ready or not inference_ready)
        self.phase = RuntimePhase.DEGRADED if degraded else RuntimePhase.RUNNING
        return RuntimeStartResult(
            ok=True,
            collector_ready=True,
            folder_index_ready=workers.index_ready,
            history_worker_ready=workers.history_ready,
            already_running=bool(collector_result.get("already_running")),
            degraded=degraded,
        )

    def shutdown(self) -> None:
        self.stop_event.set()
        inference_thread = self._inference_thread
        if inference_thread is not None:
            joiner = getattr(inference_thread, "join", None)
            if joiner is not None:
                joiner(timeout=5)
            if _thread_reference_is_alive(inference_thread):
                logging.error("inference worker did not stop before runtime shutdown")
        _synchronize_core_hooks()
        super().shutdown()


__all__ = [
    "AppRuntime",
    "RuntimePhase",
    "RuntimeStartResult",
    "WorkerReadiness",
]
