"""Timeline page adapter over the canonical report projection."""

from __future__ import annotations

from datetime import date as date_type

from . import report_projection_snapshot_service


def get_project_sessions_by_date(date: str) -> list[dict]:
    return get_project_sessions_by_range(date, date)


def get_project_sessions_by_range(
    start_date: str,
    end_date: str,
) -> list[dict]:
    return report_projection_snapshot_service.get_report_sessions_by_range(
        start_date,
        end_date,
    )


def get_default_report_date(today: date_type | None = None) -> str:
    return (today or date_type.today()).isoformat()


__all__ = [
    "get_default_report_date",
    "get_project_sessions_by_date",
    "get_project_sessions_by_range",
]
