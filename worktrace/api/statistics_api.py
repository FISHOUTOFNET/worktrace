"""Statistics facade for the UI.

Wraps ``statistics_service`` for summary totals and per-project statistics
used by the Overview and Statistics pages.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..services import statistics_service


class StatisticsSummaryError(ValueError):
    """Raised by the Phase 4A read-only statistics/export summary for known,
    user-facing failure modes.

    The ``code`` attribute is a stable token the WebView bridge maps to a
    Chinese user-facing message. Using a dedicated exception (instead of
    echoing ``ValueError`` text) keeps internal field names, ids, and SQL
    details out of bridge responses.

    Stable ``code`` values:

    - ``invalid_date`` — ``date_from`` / ``date_to`` is not a valid
      ``YYYY-MM-DD`` string.
    - ``invalid_range`` — ``date_from`` is after ``date_to``.
    - ``range_too_large`` — the inclusive span exceeds
      ``STATISTICS_SUMMARY_MAX_RANGE_DAYS`` calendar days.
    - ``operation_failed`` — race condition or unexpected service failure.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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


def get_statistics_export_summary(date_from: str, date_to: str) -> dict[str, Any]:
    """Return a read-only statistics + export-preview payload for a date range.

    Phase 4A read-only path: this method only reads closed activities and
    never writes to the DB, never writes a file, and never opens a save
    dialog. The returned payload is display-safe (no raw ``window_title``,
    ``file_path_hint``, ``full_path``, ``clipboard``, ``note``, SQL, or
    traceback).

    Raises ``StatisticsSummaryError`` with a stable ``code`` for known
    failure modes so the bridge can map to Chinese messages without echoing
    internal details.
    """
    if not isinstance(date_from, str) or not isinstance(date_to, str):
        raise StatisticsSummaryError("invalid_date")
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError:
        raise StatisticsSummaryError("invalid_date")
    if start > end:
        raise StatisticsSummaryError("invalid_range")
    if (end - start).days > statistics_service.STATISTICS_SUMMARY_MAX_RANGE_DAYS - 1:
        raise StatisticsSummaryError("range_too_large")
    try:
        return statistics_service.get_statistics_export_summary(date_from, date_to)
    except StatisticsSummaryError:
        raise
    except ValueError:
        # Defensive: the service validates too. Any ValueError that escapes
        # the validation above is treated as an operation failure so internal
        # details never reach the bridge.
        raise StatisticsSummaryError("operation_failed")
    except Exception:
        raise StatisticsSummaryError("operation_failed")


__all__ = [
    "StatisticsSummaryError",
    "get_project_stats",
    "get_statistics_export_summary",
    "get_summary",
    "get_uncategorized_duration",
]
