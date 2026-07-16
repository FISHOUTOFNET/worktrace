"""Timeline page adapter over canonical report repositories.

Session construction is owned exclusively by the canonical report projection.
This module retains only the public Timeline-facing compatibility surface.
"""

from __future__ import annotations

from datetime import date as date_type

from . import report_session_projection_service
from .report_fact_query_service import load_report_activity_rows


def get_project_sessions_by_date(date: str) -> list[dict]:
    return get_project_sessions_by_range(date, date)


def get_project_sessions_by_range(
    start_date: str,
    end_date: str,
) -> list[dict]:
    return report_session_projection_service.get_report_sessions_by_range(
        start_date,
        end_date,
    )


def get_report_activity_rows(
    start_date: str,
    end_date: str,
    include_hidden: bool = False,
    conn=None,
) -> list[dict]:
    """Compatibility adapter; canonical consumers use the fact repository."""

    if include_hidden:
        raise ValueError("hidden_report_facts_not_supported")
    return load_report_activity_rows(
        start_date,
        end_date,
        conn=conn,
    )


def get_default_report_date(today: date_type | None = None) -> str:
    return (today or date_type.today()).isoformat()


__all__ = [
    "get_default_report_date",
    "get_project_sessions_by_date",
    "get_project_sessions_by_range",
    "get_report_activity_rows",
]
