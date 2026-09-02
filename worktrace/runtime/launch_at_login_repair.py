"""Runtime-owned bounded launch-at-login repair worker."""
from __future__ import annotations

import logging
import threading

from ..platforms.startup import (
    LaunchAtLoginRepairCapability,
    LaunchAtLoginRepairError,
)
from ..worker_health import WorkerHealthReporter

_MAX_ATTEMPTS = 5
_INITIAL_DELAY_SECONDS = 1.0
_MAX_DELAY_SECONDS = 8.0


def run_launch_at_login_repair_worker(
    stop_event: threading.Event,
    repair: LaunchAtLoginRepairCapability,
    *,
    health: WorkerHealthReporter,
    max_attempts: int = _MAX_ATTEMPTS,
    initial_delay_seconds: float = _INITIAL_DELAY_SECONDS,
    max_delay_seconds: float = _MAX_DELAY_SECONDS,
) -> None:
    """Repair existing OS startup intent, then remain idle until shutdown."""

    attempt_limit = max(1, int(max_attempts))
    initial_delay = max(0.0, float(initial_delay_seconds))
    max_delay = max(initial_delay, float(max_delay_seconds))
    attempts = 0

    while not stop_event.is_set():
        attempts += 1
        logging.info("launch_at_login repair attempt attempt=%s", attempts)
        try:
            outcome = repair.repair_once()
        except LaunchAtLoginRepairError as exc:
            health.failed(exc.code)
            if exc.retryable and attempts < attempt_limit:
                delay = min(
                    max_delay,
                    initial_delay * (2 ** min(attempts - 1, 30)),
                )
                logging.warning(
                    "launch_at_login repair retry scheduled "
                    "attempt=%s next_attempt=%s delay_seconds=%.1f "
                    "code=%s operation=%s native_codes=%s",
                    attempts,
                    attempts + 1,
                    delay,
                    exc.code,
                    exc.operation,
                    list(exc.native_codes),
                    exc_info=attempts == 1,
                )
                if stop_event.wait(delay):
                    logging.info(
                        "launch_at_login repair terminal "
                        "outcome=cancelled attempts=%s",
                        attempts,
                    )
                    return
                continue

            terminal = (
                "retry_exhausted" if exc.retryable else "permanent_failure"
            )
            logging.error(
                "launch_at_login repair terminal outcome=%s attempts=%s "
                "code=%s operation=%s native_codes=%s",
                terminal,
                attempts,
                exc.code,
                exc.operation,
                list(exc.native_codes),
            )
            stop_event.wait()
            return
        except Exception:
            health.failed("launch_at_login_repair_unexpected_failure")
            logging.exception(
                "launch_at_login repair terminal "
                "outcome=permanent_failure attempts=%s "
                "code=launch_at_login_repair_unexpected_failure",
                attempts,
            )
            stop_event.wait()
            return

        health.succeeded()
        logging.info(
            "launch_at_login repair terminal outcome=%s attempts=%s",
            outcome.value,
            attempts,
        )
        stop_event.wait()
        return


__all__ = ["run_launch_at_login_repair_worker"]
