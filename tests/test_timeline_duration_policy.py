from __future__ import annotations

import pytest

from worktrace.domain_limits import (
    TIMELINE_DAY_MAX_SECONDS,
    TIMELINE_DURATION_MIN_SECONDS,
    TIMELINE_DURATION_STEP_SECONDS,
    normalize_timeline_duration_override_seconds,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


def test_timeline_duration_policy_constants_are_one_tenth_hour_and_one_day():
    assert TIMELINE_DURATION_STEP_SECONDS == 360
    assert TIMELINE_DURATION_MIN_SECONDS == 360
    assert TIMELINE_DAY_MAX_SECONDS == 86_400


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (180, 360),
        (4_442, 4_320),
        (4_500, 4_680),
        (86_400, 86_400),
        (None, None),
    ],
)
def test_duration_override_is_normalized_with_integer_half_up(seconds, expected):
    assert normalize_timeline_duration_override_seconds(seconds) == expected


@pytest.mark.parametrize("seconds", [0, 1, 3, 179])
def test_duration_override_that_normalizes_to_zero_is_too_small(seconds):
    with pytest.raises(ValueError, match="duration_too_small"):
        normalize_timeline_duration_override_seconds(seconds)


@pytest.mark.parametrize("value", [-1, True, False, 1.2, "360", float("nan"), float("inf")])
def test_duration_override_rejects_invalid_runtime_values(value):
    with pytest.raises(ValueError):
        normalize_timeline_duration_override_seconds(value)


def test_duration_override_rejects_values_above_one_day_after_normalization():
    with pytest.raises(ValueError, match="duration_exceeds_limit"):
        normalize_timeline_duration_override_seconds(86_580)
