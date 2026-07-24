"""Stable report revisions for refresh and export boundaries.

This module defines three revision concepts that must not be conflated:

* :class:`ProjectionSourceVersion` — a cheap O(1) token derived from durable
  generation counters and the database replacement epoch. It is the sole
  cache-validity and heartbeat structure signal for page read paths.

* ``snapshot_revision`` (built inside :mod:`report_projection_snapshot_service`)
  — a content hash of the complete projection output. It is computed once
  during projection build and used for mutation receipts and export
  consistency. It is NOT recomputed for cache lookups.

* ``projection_revision`` (per-session, from
  :mod:`report_projection_identity`) — a per-session identity used for
  optimistic write admission on merge/split/copy/edit.

Page and heartbeat paths use the source-version token exclusively. The
previous heavyweight content-hash path (which rescanned activities,
resources, clipboard, boundaries, operations and settings to compute a
structure revision) has been removed: it duplicated the projection build
and was never invoked from any production or test caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..db import get_connection, get_db_key
from .page_read_context import current_page_read_context
from .projection_performance import record_source_version
from .report_projection_identity import stable_json_hash

# Bump this when the projection algorithm changes shape (new fields, different
# sorting, different context attribution rules, etc.). All cached day
# projections are invalidated when this changes.
PROJECTION_SCHEMA_VERSION = 1

_STRUCTURE_GENERATION_NAMESPACES = (
    DataGenerationNamespace.REPORT_STRUCTURE,
    DataGenerationNamespace.DATABASE_REPLACEMENT,
)


@dataclass(frozen=True)
class ProjectionSourceVersion:
    """Cheap O(1) cache-validity token for day-level projections.

    Composed entirely from durable generation counters and the database
    replacement epoch — never from scanning activity rows. Two projections
    for the same ``(database_key, report_date)`` are interchangeable iff
    their source versions are equal.

    Future extension point: add ``report_day_generation`` when date-level
    generation is introduced (currently a global ``REPORT_STRUCTURE``
    counter is used, which conservatively invalidates all dates on any
    structural change).
    """

    database_key: str
    report_date: str
    report_structure_generation: int
    database_replacement_epoch: int
    projection_schema_version: int

    def token(self) -> str:
        """Stable hash token suitable for use as ``structure_revision``."""

        return stable_json_hash(
            {
                "db": self.database_key,
                "date": self.report_date,
                "gen": self.report_structure_generation,
                "epoch": self.database_replacement_epoch,
                "schema": self.projection_schema_version,
            }
        )


def get_projection_source_version(report_date: str) -> ProjectionSourceVersion:
    """Read the current source version for ``report_date`` in O(1).

    Inside a :func:`page_read_scope` the generations are reused from the
    request context (already captured). Outside, a lightweight SELECT from
    ``data_generation_state`` is used — no activity/resource/clipboard scan.
    """

    page_context = current_page_read_context()
    if page_context is not None:
        return ProjectionSourceVersion(
            database_key=page_context.database_key,
            report_date=report_date,
            report_structure_generation=int(
                page_context.report_generations.get(
                    DataGenerationNamespace.REPORT_STRUCTURE, 0
                )
            ),
            database_replacement_epoch=int(
                page_context.report_generations.get(
                    DataGenerationNamespace.DATABASE_REPLACEMENT, 0
                )
            ),
            projection_schema_version=PROJECTION_SCHEMA_VERSION,
        )

    with get_connection() as conn:
        generations = DataGenerationRepository.get_many(
            conn,
            _STRUCTURE_GENERATION_NAMESPACES,
        )
    return ProjectionSourceVersion(
        database_key=get_db_key(),
        report_date=report_date,
        report_structure_generation=int(
            generations.get(DataGenerationNamespace.REPORT_STRUCTURE, 0)
        ),
        database_replacement_epoch=int(
            generations.get(DataGenerationNamespace.DATABASE_REPLACEMENT, 0)
        ),
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
    )


def clear_report_structure_revision_cache(database_key: str | None = None) -> None:
    """No-op retained for backward compatibility.

    The source-version token is O(1) and needs no cache. This hook is kept
    so existing test isolation calls continue to compile; it has no effect.
    """

    return None


def get_report_structure_revision(report_date: str) -> str:
    """Return the structural revision used by pages and heartbeat.

    This is the cheap :class:`ProjectionSourceVersion` token — an O(1)
    value derived from durable generation counters, never from scanning
    activity rows. Callers that need a content hash of the actual
    projection output must use ``snapshot_revision`` from
    :func:`report_projection_snapshot_service.build_visible_snapshot`
    (computed once during projection build).
    """

    date_type.fromisoformat(report_date)
    source_version = get_projection_source_version(report_date)
    token = source_version.token()
    record_source_version(token)
    return token


def export_revision(date_from: str, date_to: str, records) -> str:
    """Revision of the exact closed, display-safe export record set."""

    return stable_json_hash(
        {
            "range": [date_from, date_to],
            "records": [dict(record) for record in records],
        }
    )


__all__ = [
    "PROJECTION_SCHEMA_VERSION",
    "ProjectionSourceVersion",
    "clear_report_structure_revision_cache",
    "export_revision",
    "get_projection_source_version",
    "get_report_structure_revision",
]
