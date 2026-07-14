from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from ..constants import TIME_FORMAT

if TYPE_CHECKING:
    from .state_machine import CollectorStateMachine


@dataclass(frozen=True)
class ClockDiscontinuity:
    reason: str
    safe_end_time: str
    wall_delta_seconds: float
    monotonic_delta_seconds: float


class ClockTracker:
    """Own clock discontinuity detection and its continuity-boundary policy."""

    def __init__(self) -> None:
        self._last_wall: datetime | None = None
        self._last_monotonic: float | None = None

    def observe(
        self,
        wall_time: str,
        monotonic_time: float,
        *,
        clock_jump_threshold_seconds: int,
        stall_threshold_seconds: int,
    ) -> ClockDiscontinuity | None:
        current_wall = datetime.strptime(wall_time, TIME_FORMAT)
        current_monotonic = float(monotonic_time)
        previous_wall = self._last_wall
        previous_monotonic = self._last_monotonic
        self._last_wall = current_wall
        self._last_monotonic = current_monotonic
        if previous_wall is None or previous_monotonic is None:
            return None

        monotonic_delta = max(0.0, current_monotonic - previous_monotonic)
        wall_delta = (current_wall - previous_wall).total_seconds()
        stall_threshold = max(1, int(stall_threshold_seconds or 0))
        jump_threshold = max(1, int(clock_jump_threshold_seconds or 0))

        if monotonic_delta > stall_threshold:
            return ClockDiscontinuity(
                reason="collector_stall",
                safe_end_time=previous_wall.strftime(TIME_FORMAT),
                wall_delta_seconds=wall_delta,
                monotonic_delta_seconds=monotonic_delta,
            )

        drift = wall_delta - monotonic_delta
        if abs(drift) <= jump_threshold:
            return None

        if drift < 0:
            safe_end = current_wall
            reason = "clock_jump_backward"
        else:
            safe_end = previous_wall + timedelta(seconds=monotonic_delta)
            reason = "clock_jump_forward"
        return ClockDiscontinuity(
            reason=reason,
            safe_end_time=safe_end.strftime(TIME_FORMAT),
            wall_delta_seconds=wall_delta,
            monotonic_delta_seconds=monotonic_delta,
        )

    @staticmethod
    def apply_discontinuity(
        machine: "CollectorStateMachine",
        discontinuity: ClockDiscontinuity,
    ) -> None:
        """Apply the clock policy outside the collector loop's orchestration code."""
        machine.reset_for_time_jump(discontinuity.safe_end_time)


__all__ = ["ClockDiscontinuity", "ClockTracker"]
