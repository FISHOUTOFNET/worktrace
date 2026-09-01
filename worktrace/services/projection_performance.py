"""Low-noise performance instrumentation for the daily projection read path.

This module is the single owner of stage timing for report projection reads.
It records one :class:`ProjectionPerfRecord` per page request, accumulates
stage elapsed durations via :func:`stage`, and emits a single structured
warning log when the request exceeds the configured elapsed-time threshold.
Fast requests pay only a pair of ``time.perf_counter`` calls per stage and
never emit log output.

Timing contract:
* ``total_ms`` and ``*_ms`` stage fields are elapsed durations measured with
  :func:`time.perf_counter`. They include time when the request thread is not
  executing, including blocking, scheduling delays, and system suspend.
* ``total_cpu_ms`` is measured with :func:`time.thread_time` and records CPU
  actually consumed by the request thread. It is diagnostic only and never
  changes slow-request classification.

Privacy contract: only aggregate counts, cache-hit flag, source-version token
and timing data are recorded. Window titles, file paths, resource names and
other payload fragments are never captured.

Testability: :func:`get_last_record` exposes the most recent record for direct
assertion without relying on log capture, and :func:`set_threshold_ms` lets
tests force emission of the slow-request log.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

_logger = logging.getLogger("worktrace.projection_perf")

_DEFAULT_THRESHOLD_MS = 200.0
_threshold_lock = threading.Lock()
_threshold_ms: float = _DEFAULT_THRESHOLD_MS

_last_record_lock = threading.Lock()
_last_record: "ProjectionPerfRecord | None" = None

_local = threading.local()


@dataclass
class ProjectionPerfRecord:
    """Aggregate timing for one projection read request."""

    report_date: str = ""
    activity_count: int = 0
    entry_count: int = 0
    contribution_count: int = 0
    cache_hit: bool = False
    source_version: str = ""
    surface: str = ""
    stages: dict[str, float] = field(default_factory=dict)
    total_ms: float = 0.0
    total_cpu_ms: float = 0.0

    def stage_total(self, name: str) -> float:
        return float(self.stages.get(name, 0.0))

    def to_log_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "report_date": self.report_date,
            "surface": self.surface,
            "activity_count": self.activity_count,
            "entry_count": self.entry_count,
            "contribution_count": self.contribution_count,
            "cache_hit": self.cache_hit,
            "source_version": self.source_version,
            "total_ms": round(self.total_ms, 2),
            "total_cpu_ms": round(self.total_cpu_ms, 2),
        }
        for name, value in self.stages.items():
            payload[f"{name}_ms"] = round(value, 2)
        return payload


def set_threshold_ms(value: float) -> None:
    """Override the slow-request log threshold. Use 0 to always emit."""

    global _threshold_ms
    with _threshold_lock:
        _threshold_ms = max(0.0, float(value))


def get_threshold_ms() -> float:
    with _threshold_lock:
        return _threshold_ms


def get_last_record() -> "ProjectionPerfRecord | None":
    with _last_record_lock:
        return _last_record


def reset_last_record() -> None:
    """Forget the last captured record. Test-only hook."""

    global _last_record
    with _last_record_lock:
        _last_record = None


def _current_record() -> "ProjectionPerfRecord | None":
    return getattr(_local, "record", None)


@contextmanager
def projection_perf_scope(
    report_date: str,
    *,
    surface: str = "",
) -> Iterator[ProjectionPerfRecord]:
    """Bind a per-request perf record.

    Nested scopes (e.g. detail lookup inside a bridge call) reuse the
    outermost record so a single page request produces one aggregated entry.
    """

    existing = _current_record()
    if existing is not None:
        if not existing.report_date:
            existing.report_date = report_date
        if not existing.surface:
            existing.surface = surface
        yield existing
        return

    record = ProjectionPerfRecord(report_date=report_date, surface=surface)
    _local.record = record
    elapsed_start = time.perf_counter()
    cpu_start = time.thread_time()
    try:
        yield record
    finally:
        record.total_ms = (time.perf_counter() - elapsed_start) * 1000.0
        record.total_cpu_ms = (time.thread_time() - cpu_start) * 1000.0
        _local.record = None
        with _last_record_lock:
            global _last_record
            _last_record = record
        threshold = get_threshold_ms()
        if record.total_ms >= threshold:
            _logger.warning(
                "projection_perf_slow %s",
                record.to_log_payload(),
            )


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Accumulate elapsed duration under ``name`` on the active record.

    Outside a :func:`projection_perf_scope` the context manager is a no-op so
    production callers (mutation transactions, internal helpers) can instrument
    shared code without forcing every caller to bind a scope.
    """

    record = _current_record()
    if record is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        delta = (time.perf_counter() - start) * 1000.0
        record.stages[name] = record.stages.get(name, 0.0) + delta


def record_counts(
    *,
    activity_count: int,
    entry_count: int,
    contribution_count: int,
) -> None:
    """Stamp the projection size on the active record, if any."""

    record = _current_record()
    if record is None:
        return
    record.activity_count = int(activity_count)
    record.entry_count = int(entry_count)
    record.contribution_count = int(contribution_count)


def record_cache_hit(value: bool) -> None:
    record = _current_record()
    if record is None:
        return
    record.cache_hit = bool(value)


def record_source_version(token: str) -> None:
    record = _current_record()
    if record is None:
        return
    record.source_version = str(token or "")


__all__ = [
    "ProjectionPerfRecord",
    "get_last_record",
    "get_threshold_ms",
    "projection_perf_scope",
    "record_cache_hit",
    "record_counts",
    "record_source_version",
    "reset_last_record",
    "set_threshold_ms",
    "stage",
]
