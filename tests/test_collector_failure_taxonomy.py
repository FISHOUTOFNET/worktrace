from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from worktrace.collector.collector_failure_policy import (
    CollectorFailureCode,
    TransientCollectorError,
    classify_collector_failure,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.collector_runtime]

ROOT = Path(__file__).resolve().parents[1]


def test_unknown_failures_are_fatal_by_default():
    for exc in (
        RuntimeError("broken invariant"),
        ValueError("bad payload"),
        IndexError("bad index"),
        TimeoutError("unclassified timeout"),
        sqlite3.DatabaseError("database disk image is malformed"),
    ):
        disposition = classify_collector_failure(exc)
        assert disposition.code is CollectorFailureCode.UNEXPECTED_FAILURE
        assert disposition.retryable is False


def test_controlled_database_contention_is_retryable():
    for exc in (
        sqlite3.OperationalError("database is locked"),
        sqlite3.OperationalError("database table is locked"),
        sqlite3.OperationalError("database is busy"),
    ):
        disposition = classify_collector_failure(exc)
        assert disposition.code is CollectorFailureCode.DATABASE_BUSY
        assert disposition.retryable is True


def test_internal_database_gate_codes_are_retryable():
    expected = {
        "secure_import_in_progress": CollectorFailureCode.SECURE_IMPORT_IN_PROGRESS,
        "database_generation_changed": CollectorFailureCode.DATABASE_GENERATION_CHANGED,
    }
    for raw, code in expected.items():
        disposition = classify_collector_failure(sqlite3.OperationalError(raw))
        assert disposition.code is code
        assert disposition.retryable is True


def test_explicit_adapter_failure_is_retryable():
    disposition = classify_collector_failure(
        TransientCollectorError(
            CollectorFailureCode.ADAPTER_TEMPORARILY_UNAVAILABLE
        )
    )
    assert disposition.code is CollectorFailureCode.ADAPTER_TEMPORARILY_UNAVAILABLE
    assert disposition.retryable is True


def test_collector_health_never_receives_or_classifies_raw_failures():
    health_source = (
        ROOT / "worktrace/collector/collector_health.py"
    ).read_text(encoding="utf-8")
    collector_source = (
        ROOT / "worktrace/collector/collector.py"
    ).read_text(encoding="utf-8")

    assert "BaseException" not in health_source
    assert "sqlite3" not in health_source
    assert "is_transient_failure" not in health_source
    assert "classify_collector_failure" not in health_source
    assert "classify_collector_failure" in collector_source
    assert "is_transient_failure" not in collector_source
    assert "logging.exception" not in collector_source
    assert "type(exc).__name__" not in collector_source
