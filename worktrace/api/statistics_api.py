"""Statistics facade for the UI.

Wraps ``statistics_service`` for summary totals and per-project statistics
used by the Overview and Statistics pages.
"""

from __future__ import annotations

from typing import Any

from ..services import statistics_service


def get_summary(
    start_date: str,
    end_date: str,
    ensure_context: bool = True,
    include_live: bool = False,
) -> dict[str, Any]:
    return statistics_service.get_summary(
        start_date,
        end_date,
        ensure_context=ensure_context,
        include_live=include_live,
    )


def get_project_stats(
    start_date: str,
    end_date: str,
    ensure_context: bool = True,
    include_live: bool = False,
) -> list[dict[str, Any]]:
    return statistics_service.get_project_stats(
        start_date,
        end_date,
        ensure_context=ensure_context,
        include_live=include_live,
    )


def get_uncategorized_duration(start_date: str, end_date: str) -> int:
    return statistics_service.get_uncategorized_duration(start_date, end_date)


__all__ = ["get_project_stats", "get_summary", "get_uncategorized_duration"]
