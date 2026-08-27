"""Compact range projection for interactive Statistics reads.

Statistics pages need the same projection semantics as canonical report snapshots,
but they do not need mutation/export-only collections such as ``base_sessions`` or
separately frozen session subsets.  This module materializes only final entries and
contributions, stores them once, and builds reference-only lookup indexes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .report_projection_builder import ProjectionComputation
from .report_projection_model import OperationDiagnostic
from .report_projection_provider import (
    build_projection_indexes,
    freeze_projection_data,
)


@dataclass(frozen=True, slots=True)
class StatisticsRangeSourceVersion:
    """Durable source version for one Statistics range cache entry."""

    database_key: str
    report_structure_generation: int
    database_replacement_epoch: int
    projection_schema_version: int

    def token(self) -> str:
        return ":".join(
            (
                self.database_key,
                str(self.report_structure_generation),
                str(self.database_replacement_epoch),
                str(self.projection_schema_version),
            )
        )


@dataclass(frozen=True, slots=True)
class StatisticsRangeProjection:
    """Compact immutable range projection used only by interactive Statistics."""

    start_date: str
    end_date: str
    source_version: StatisticsRangeSourceVersion
    entries: tuple[Mapping[str, Any], ...]
    contributions: tuple[Mapping[str, Any], ...]
    operation_diagnostics: tuple[OperationDiagnostic, ...]
    snapshot_revision: str
    entry_by_key: Mapping[str, Mapping[str, Any]]
    contributions_by_key: Mapping[str, tuple[Mapping[str, Any], ...]]

    @property
    def final_entries(self) -> tuple[Mapping[str, Any], ...]:
        return self.entries

    @property
    def final_contributions(self) -> tuple[Mapping[str, Any], ...]:
        return self.contributions

    @property
    def final_sessions(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            entry
            for entry in self.entries
            if str(entry.get("row_kind") or "project_session") == "project_session"
        )

    @property
    def standalone_status_entries(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            entry
            for entry in self.entries
            if str(entry.get("row_kind") or "") == "standalone_status"
        )


def materialize_statistics_range_projection(
    computation: ProjectionComputation,
    source_version: StatisticsRangeSourceVersion,
    *,
    start_date: str,
    end_date: str,
) -> StatisticsRangeProjection:
    """Freeze only the collections Statistics page reads actually consume."""

    frozen_data = freeze_projection_data(computation)
    indexes = build_projection_indexes(frozen_data)
    return StatisticsRangeProjection(
        start_date=str(start_date),
        end_date=str(end_date),
        source_version=source_version,
        entries=frozen_data.entries,
        contributions=frozen_data.contributions,
        operation_diagnostics=frozen_data.operation_diagnostics,
        snapshot_revision=frozen_data.snapshot_revision,
        entry_by_key=indexes.entry_by_key,
        contributions_by_key=indexes.contributions_by_key,
    )


__all__ = [
    "StatisticsRangeProjection",
    "StatisticsRangeSourceVersion",
    "materialize_statistics_range_projection",
]
