"""Shipping UI range policy for Statistics and CSV export.

The core statistics service intentionally retains its all-time transport
semantics for compatibility and future optimized implementations.  This
application-boundary policy keeps the current interactive surface bounded so
it cannot materialize an unbounded historical snapshot before that work lands.
"""
from __future__ import annotations

from datetime import date

from ..services import statistics_service


INTERACTIVE_STATISTICS_MAX_RANGE_DAYS = 366


def validate_interactive_statistics_range(date_from: str, date_to: str) -> None:
    """Reject all-time and explicit ranges larger than the shipping UI budget."""

    if date_from == "" and date_to == "":
        raise ValueError("range_too_large")

    statistics_service.validate_statistics_date_range(date_from, date_to)
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    inclusive_days = (end - start).days + 1
    if inclusive_days > INTERACTIVE_STATISTICS_MAX_RANGE_DAYS:
        raise ValueError("range_too_large")


__all__ = [
    "INTERACTIVE_STATISTICS_MAX_RANGE_DAYS",
    "validate_interactive_statistics_range",
]
