"""Aggregate application-control facade for the UI.

Holds a module-level reference to the ``AppRuntime`` so the UI can request
collector start and shutdown without importing ``worktrace.runtime`` or holding
the stop event directly. This module is intentionally light: it is not a god
object. UI code may also import the specific api modules directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..services.runtime_activity_state_service import record_runtime_boundary
from . import settings_api

if TYPE_CHECKING:
    from ..runtime.app_runtime import AppRuntime

_runtime: "AppRuntime | None" = None


def set_runtime(runtime: "AppRuntime | None") -> None:
    """Register the active ``AppRuntime`` instance. Called once during startup."""
    global _runtime
    _runtime = runtime


def get_runtime() -> "AppRuntime | None":
    return _runtime


def start_collection_after_privacy_gate() -> dict[str, Any]:
    """Unified startup entry that enforces the first-run privacy gate.

    Fail-closed: if the notice has not been accepted (or the read raises),
    no worker / collector starts and caller state is not mutated. On
    success starts ``start_background_workers`` BEFORE
    ``start_collector`` (folder index warm-up) and returns ``{"ok": True}``.
    """
    try:
        notice_accepted = settings_api.first_run_notice_accepted()
    except Exception:
        logging.exception(
            "app_api.start_collection_after_privacy_gate: first-run "
            "notice read failed; failing closed"
        )
        return {"ok": False, "error": "请先确认隐私说明"}
    if not notice_accepted:
        return {"ok": False, "error": "请先确认隐私说明"}
    try:
        if _runtime is not None:
            _runtime.start_background_workers()
    except Exception:
        logging.exception(
            "app_api.start_collection_after_privacy_gate: background "
            "workers start failed after gate passed"
        )
    try:
        if _runtime is not None:
            _runtime.start_collector()
    except Exception:
        logging.exception(
            "app_api.start_collection_after_privacy_gate: collector "
            "start failed after gate passed"
        )
    return {"ok": True}


def pause_collection_now() -> dict[str, Any]:
    """Pause collection through the runtime/collector lifecycle owner.

    The UI must not clear ``current_activity_snapshot`` itself. When no
    collector can acknowledge the command, fail safe by marking the user
    paused so the next collector loop closes the activity; snapshot cleanup
    remains recorder-owned.
    """
    try:
        if _runtime is not None:
            return dict(_runtime.pause_collection_now())
        settings_api.set_user_paused(True)
        record_runtime_boundary("pause_api_fallback")
        return {"ok": False, "pause_pending": True}
    except Exception:
        logging.exception("app_api.pause_collection_now failed")
        try:
            settings_api.set_user_paused(True)
            record_runtime_boundary("pause_api_exception_fallback")
        except Exception:
            logging.exception("app_api.pause_collection_now fallback failed")
        return {"ok": False, "pause_pending": True}


def start_collector() -> None:
    """Start the collector thread if it has not been started yet.

    Runtime-internal helper. UI callers MUST go through
    :func:`start_collection_after_privacy_gate` so the privacy gate is
    enforced in exactly one place.
    """
    if _runtime is not None:
        _runtime.start_collector()


def start_background_workers() -> bool:
    """Start background workers (folder index worker) if not started yet.

    Runtime-internal helper. UI callers MUST go through
    :func:`start_collection_after_privacy_gate` so the privacy gate is
    enforced in exactly one place. Returns ``True`` when this call
    actually started the worker, ``False`` when already running or this
    instance does not own the collector.
    """
    if _runtime is not None:
        return _runtime.start_background_workers()
    return False


def request_shutdown() -> None:
    """Signal the collector and index threads to stop.

    Called by the UI when the user exits from the tray or closes the window
    without a tray. The actual thread join and cleanup happens in
    ``AppRuntime.shutdown``.
    """
    if _runtime is not None:
        _runtime.request_shutdown()


def owns_collector() -> bool:
    """Whether this process instance owns the collector."""
    if _runtime is not None:
        return _runtime.owns_collector
    return False


__all__ = [
    "get_runtime",
    "owns_collector",
    "pause_collection_now",
    "request_shutdown",
    "set_runtime",
    "start_background_workers",
    "start_collection_after_privacy_gate",
    "start_collector",
]
