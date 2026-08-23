"""Shared reported-duration semantics for Timeline totals and mutations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import chain
from typing import Any


def reported_entry_duration_seconds(entry: Mapping[str, Any]) -> int:
    if entry.get("contributes_to_totals", True) is False:
        return 0
    value = entry.get("report_duration_seconds")
    if value is None:
        value = entry.get("duration_seconds")
    return max(0, int(value or 0))


def reported_day_total_seconds(
    project_sessions: Iterable[Mapping[str, Any]],
    standalone_entries: Iterable[Mapping[str, Any]] = (),
) -> int:
    return sum(
        reported_entry_duration_seconds(entry)
        for entry in chain(project_sessions, standalone_entries)
    )


__all__ = ["reported_day_total_seconds", "reported_entry_duration_seconds"]
