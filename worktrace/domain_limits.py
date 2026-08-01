"""Shared durable-domain limits used by every ingress boundary."""

NOTE_MAX_LENGTH = 2000
TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH = 200
TIMELINE_DURATION_STEP_SECONDS = 360
TIMELINE_DURATION_MIN_SECONDS = 360
TIMELINE_DAY_MAX_SECONDS = 24 * 60 * 60
ADJUSTED_DURATION_MAX_SECONDS = TIMELINE_DAY_MAX_SECONDS


def normalize_timeline_duration_override_seconds(value: int | None) -> int | None:
    """Normalize a non-empty Timeline override to deterministic 0.1h steps."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid_duration")
    if value < 0:
        raise ValueError("invalid_duration")
    rounded = (
        (value + TIMELINE_DURATION_STEP_SECONDS // 2)
        // TIMELINE_DURATION_STEP_SECONDS
    ) * TIMELINE_DURATION_STEP_SECONDS
    if rounded < TIMELINE_DURATION_MIN_SECONDS:
        raise ValueError("duration_too_small")
    if rounded > TIMELINE_DAY_MAX_SECONDS:
        raise ValueError("duration_exceeds_limit")
    return rounded

__all__ = [
    "ADJUSTED_DURATION_MAX_SECONDS",
    "NOTE_MAX_LENGTH",
    "TIMELINE_DAY_MAX_SECONDS",
    "TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH",
    "TIMELINE_DURATION_MIN_SECONDS",
    "TIMELINE_DURATION_STEP_SECONDS",
    "normalize_timeline_duration_override_seconds",
]
