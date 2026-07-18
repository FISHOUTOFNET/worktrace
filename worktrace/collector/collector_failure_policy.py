"""Safe classification boundary for Collector failures.

Raw exceptions are inspected only here. Callers receive a bounded code and a
retry decision; exception text must never cross into Collector health state or
operational logging.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum


class CollectorFailureCode(str, Enum):
    DATABASE_BUSY = "database_busy"
    SECURE_IMPORT_IN_PROGRESS = "secure_import_in_progress"
    DATABASE_GENERATION_CHANGED = "database_generation_changed"
    ADAPTER_TEMPORARILY_UNAVAILABLE = "adapter_temporarily_unavailable"
    UNEXPECTED_FAILURE = "unexpected_failure"


@dataclass(frozen=True)
class CollectorFailureDisposition:
    code: CollectorFailureCode
    retryable: bool


class TransientCollectorError(RuntimeError):
    """Explicitly declare a bounded infrastructure failure as retryable."""

    def __init__(self, code: CollectorFailureCode) -> None:
        if code not in {
            CollectorFailureCode.ADAPTER_TEMPORARILY_UNAVAILABLE,
            CollectorFailureCode.DATABASE_BUSY,
            CollectorFailureCode.SECURE_IMPORT_IN_PROGRESS,
            CollectorFailureCode.DATABASE_GENERATION_CHANGED,
        }:
            raise ValueError("collector_failure_code_not_retryable")
        self.code = code
        super().__init__(code.value)


def classify_collector_failure(exc: BaseException) -> CollectorFailureDisposition:
    """Return a safe, closed taxonomy for one raw Collector exception."""

    if isinstance(exc, TransientCollectorError):
        return CollectorFailureDisposition(exc.code, True)

    if isinstance(exc, sqlite3.OperationalError):
        sqlite_code = getattr(exc, "sqlite_errorcode", None)
        if sqlite_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return CollectorFailureDisposition(
                CollectorFailureCode.DATABASE_BUSY,
                True,
            )
        message = str(exc).strip().lower()
        if message == CollectorFailureCode.SECURE_IMPORT_IN_PROGRESS.value:
            return CollectorFailureDisposition(
                CollectorFailureCode.SECURE_IMPORT_IN_PROGRESS,
                True,
            )
        if message == CollectorFailureCode.DATABASE_GENERATION_CHANGED.value:
            return CollectorFailureDisposition(
                CollectorFailureCode.DATABASE_GENERATION_CHANGED,
                True,
            )

    return CollectorFailureDisposition(
        CollectorFailureCode.UNEXPECTED_FAILURE,
        False,
    )


__all__ = [
    "CollectorFailureCode",
    "CollectorFailureDisposition",
    "TransientCollectorError",
    "classify_collector_failure",
]
