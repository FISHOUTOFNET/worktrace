"""Statistics facade for the UI.

Wraps ``statistics_service`` for summary totals and per-project statistics
used by the Overview and Statistics pages.
"""

from __future__ import annotations

from typing import Any

from ..services import statistics_service


class StatisticsSummaryError(ValueError):
    """Raised by the read-only statistics/export summary for known user-facing failures.
    user-facing failure modes.

    The ``code`` attribute is a stable token the WebView bridge maps to a
    Chinese message, so internal field names, ids, and SQL details never
    reach the bridge.
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

    Read-only path: only reads closed activities and never writes to the DB,
    never writes a file, and never opens a save dialog. The returned payload
    is display-safe (no raw ``window_title``, ``file_path_hint``,
    ``full_path``, ``clipboard``, ``note``, SQL, or traceback).
    traceback).

    Raises ``StatisticsSummaryError`` with a stable ``code`` for known
    failure modes so the bridge can map to Chinese messages without echoing
    internal details.

    The service layer performs the canonical date validation; this wrapper
    maps ``ValueError`` (with its stable code token) to
    ``StatisticsSummaryError`` and collapses any unexpected exception to
    ``operation_failed`` so internal details never reach the bridge.
    bridge.
    """
    try:
        return statistics_service.get_statistics_export_summary(date_from, date_to)
    except StatisticsSummaryError:
        raise
    except ValueError as exc:
        # The service raises ValueError with a stable code token
        # (``invalid_date`` / ``invalid_range`` / ``range_too_large``).
        # Map it to StatisticsSummaryError; unknown ValueError text collapses
        # to ``operation_failed`` so internal details never reach the bridge.
        code = str(exc)
        if code in ("invalid_date", "invalid_range", "range_too_large"):
            raise StatisticsSummaryError(code)
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
