"""Process-local retry episode state with no I/O or lifecycle ownership."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RetryDecision:
    code: str
    attempt: int
    delay_seconds: float
    elapsed_seconds: float
    first_failure: bool
    code_changed: bool
    detail_log_due: bool
    summary_log_due: bool


@dataclass(frozen=True)
class RecoveryDecision:
    recovered: bool
    code: str = ""
    attempts: int = 0
    elapsed_seconds: float = 0.0


class RetryEpisode:
    """Track one worker-local failure episode without performing side effects."""

    def __init__(
        self,
        *,
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        summary_interval_seconds: float = 60.0,
        monotonic_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._initial_delay = max(0.0, float(initial_delay_seconds))
        self._max_delay = max(self._initial_delay, float(max_delay_seconds))
        self._summary_interval = max(0.0, float(summary_interval_seconds))
        self._monotonic = monotonic_func
        self._code = ""
        self._attempts = 0
        self._started_at = 0.0
        self._last_summary_at = 0.0

    def failed(self, code: str) -> RetryDecision:
        now = self._monotonic()
        normalized = str(code or "retryable_failure").strip() or "retryable_failure"
        first_failure = self._attempts == 0
        code_changed = bool(not first_failure and normalized != self._code)
        if first_failure or code_changed:
            self._code = normalized
            self._attempts = 1
            self._started_at = now
            self._last_summary_at = now
        else:
            self._attempts += 1

        detail_log_due = bool(first_failure or code_changed)
        summary_log_due = False
        if (
            not detail_log_due
            and self._summary_interval > 0.0
            and now - self._last_summary_at >= self._summary_interval
        ):
            summary_log_due = True
            self._last_summary_at = now

        if self._initial_delay <= 0.0:
            delay_seconds = 0.0
        else:
            delay_seconds = min(
                self._max_delay,
                self._initial_delay * (2 ** min(self._attempts - 1, 30)),
            )
        return RetryDecision(
            code=self._code,
            attempt=self._attempts,
            delay_seconds=delay_seconds,
            elapsed_seconds=max(0.0, now - self._started_at),
            first_failure=first_failure,
            code_changed=code_changed,
            detail_log_due=detail_log_due,
            summary_log_due=summary_log_due,
        )

    def succeeded(self) -> RecoveryDecision:
        if self._attempts <= 0:
            return RecoveryDecision(False)
        now = self._monotonic()
        recovered = RecoveryDecision(
            True,
            code=self._code,
            attempts=self._attempts,
            elapsed_seconds=max(0.0, now - self._started_at),
        )
        self._code = ""
        self._attempts = 0
        self._started_at = 0.0
        self._last_summary_at = 0.0
        return recovered


__all__ = ["RecoveryDecision", "RetryDecision", "RetryEpisode"]
