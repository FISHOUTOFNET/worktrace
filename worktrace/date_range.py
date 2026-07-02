"""Pure date-range calculation utilities.

Contains no tkinter/customtkinter imports and is reusable across UI backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DateRange:
    start: str
    end: str
    kind: str


def today_range(today_text: str) -> DateRange:
    return DateRange(today_text, today_text, "day")


def current_week_range(today_text: str) -> DateRange:
    today = date.fromisoformat(today_text)
    start = today - timedelta(days=today.weekday())
    return DateRange(start.isoformat(), today.isoformat(), "week")


def previous_week_range(today_text: str) -> DateRange:
    today = date.fromisoformat(today_text)
    this_week_start = today - timedelta(days=today.weekday())
    start = this_week_start - timedelta(days=7)
    end = start + timedelta(days=6)
    return DateRange(start.isoformat(), end.isoformat(), "week")


def classify_range(start_text: str, end_text: str) -> str:
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
    except ValueError:
        return "custom"
    if start == end:
        return "day"
    if start.weekday() == 0 and 0 <= (end - start).days <= 6:
        return "week"
    return "custom"


def shift_range(start_text: str, end_text: str, direction: int) -> DateRange | None:
    kind = classify_range(start_text, end_text)
    if kind == "custom":
        return None
    start = date.fromisoformat(start_text)
    end = date.fromisoformat(end_text)
    days = 1 if kind == "day" else 7
    delta = timedelta(days=days * (1 if direction >= 0 else -1))
    return DateRange((start + delta).isoformat(), (end + delta).isoformat(), kind)
