import pytest

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]

from worktrace import date_range


def test_quick_ranges_use_iso_weeks():
    today = "2026-06-20"

    assert date_range.today_range(today) == date_range.DateRange("2026-06-20", "2026-06-20", "day")
    assert date_range.current_week_range(today) == date_range.DateRange("2026-06-15", "2026-06-20", "week")
    assert date_range.previous_week_range(today) == date_range.DateRange("2026-06-08", "2026-06-14", "week")


def test_shift_range_moves_days_and_weeks_but_not_custom_ranges():
    assert date_range.shift_range("2026-06-20", "2026-06-20", -1) == date_range.DateRange(
        "2026-06-19", "2026-06-19", "day"
    )
    assert date_range.shift_range("2026-06-15", "2026-06-20", -1) == date_range.DateRange(
        "2026-06-08", "2026-06-13", "week"
    )
    assert date_range.shift_range("2026-06-17", "2026-06-20", -1) is None
