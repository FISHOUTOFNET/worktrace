"""Process-local platform capability health without worker semantics."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

_PATH_FAILURE_THRESHOLD = 3
_TECHNICAL_FAILURE_OUTCOMES = frozenset({"timeout", "helper_error"})


@dataclass(frozen=True)
class PathCapabilityHealthSnapshot:
    state: str = "unknown"
    last_failure_code: str = ""
    consecutive_failures: int = 0

    def to_public_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "last_failure_code": self.last_failure_code,
            "consecutive_failures": self.consecutive_failures,
        }


class PathCapabilityHealth:
    """Track on-demand path capability without pretending it is a worker."""

    def __init__(self, *, failure_threshold: int = _PATH_FAILURE_THRESHOLD) -> None:
        self._lock = threading.RLock()
        self._failure_threshold = max(1, int(failure_threshold))
        self._state = "unknown"
        self._last_failure_code = ""
        self._consecutive_failures = 0

    def snapshot(self) -> PathCapabilityHealthSnapshot:
        with self._lock:
            return PathCapabilityHealthSnapshot(
                state=self._state,
                last_failure_code=self._last_failure_code,
                consecutive_failures=self._consecutive_failures,
            )

    def mark_recovering(self) -> None:
        with self._lock:
            previous = self._state
            self._state = "recovering"
            self._last_failure_code = ""
            self._consecutive_failures = 0
        if previous != "recovering":
            logging.info("path capability path_capability_state=recovering reason=runtime_reset")

    def mark_unknown(self) -> None:
        with self._lock:
            self._state = "unknown"
            self._last_failure_code = ""
            self._consecutive_failures = 0

    def observe_probe(
        self,
        *,
        route: str,
        outcome: str,
        attempted: bool,
        path_found: bool,
    ) -> None:
        if not attempted:
            return
        safe_route = str(route or "unknown").strip().lower() or "unknown"
        safe_outcome = str(outcome or "unknown").strip().lower() or "unknown"
        if path_found and safe_outcome == "success":
            with self._lock:
                previous = self._state
                failures = self._consecutive_failures
                self._state = "healthy"
                self._last_failure_code = ""
                self._consecutive_failures = 0
            if previous != "healthy" or failures:
                logging.info(
                    "path capability path_capability_state=healthy "
                    "path_probe_route=%s recovered=%s prior_failures=%s",
                    safe_route,
                    str(previous in {"recovering", "degraded"}).lower(),
                    failures,
                )
            return

        if safe_outcome not in _TECHNICAL_FAILURE_OUTCOMES:
            return

        code = f"{safe_route}_{safe_outcome}"[:64]
        with self._lock:
            previous = self._state
            self._consecutive_failures += 1
            failures = self._consecutive_failures
            self._last_failure_code = code
            if previous == "recovering" or failures >= self._failure_threshold:
                self._state = "degraded"
            current = self._state
        if current == "degraded" and previous != "degraded":
            logging.warning(
                "path capability path_capability_state=degraded last_failure_code=%s consecutive_failures=%s",
                code,
                failures,
            )


__all__ = ["PathCapabilityHealth", "PathCapabilityHealthSnapshot"]
