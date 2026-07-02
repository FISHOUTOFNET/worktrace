"""Aggregate application-control facade for the UI.

Holds a module-level reference to the ``AppRuntime`` so the UI can request
collector start and shutdown without importing ``worktrace.runtime`` or holding
the stop event directly. This module is intentionally light: it is not a god
object. UI code may also import the specific api modules directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime.app_runtime import AppRuntime

_runtime: "AppRuntime | None" = None


def set_runtime(runtime: "AppRuntime | None") -> None:
    """Register the active ``AppRuntime`` instance. Called once during startup."""
    global _runtime
    _runtime = runtime


def get_runtime() -> "AppRuntime | None":
    return _runtime


def start_collector() -> None:
    """Start the collector thread if it has not been started yet."""
    if _runtime is not None:
        _runtime.start_collector()


def start_background_workers() -> bool:
    """Start background workers (folder index worker) if not started yet.

    Returns ``True`` when this call actually started the worker, ``False``
    when already running or this instance does not own the collector.

    Callers must only invoke this after the first-run privacy notice has
    been accepted: the folder index worker probes local
    accepted: the folder index worker probes local
    ``os.path.exists(file_path)`` paths for ready indexes.
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
    "request_shutdown",
    "set_runtime",
    "start_background_workers",
    "start_collector",
]
