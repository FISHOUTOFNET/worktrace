from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from worktrace.collector import collector as collector_module
from worktrace.collector import collector_health
from worktrace.collector.collector_failure_policy import (
    CollectorFailureCode,
    TransientCollectorError,
    classify_collector_failure,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.db,
    pytest.mark.contract,
    pytest.mark.collector_runtime,
]

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


def test_failure_health_api_requires_enum_codes():
    with pytest.raises(TypeError, match="collector_failure_code_required"):
        collector_health.record_transient_failure(
            "clipboard",
            "database_busy",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="collector_failure_code_required"):
        collector_health.record_fatal_failure(
            "startup",
            "unexpected_failure",  # type: ignore[arg-type]
        )


def test_transient_health_api_rejects_non_retryable_codes():
    with pytest.raises(ValueError, match="collector_failure_code_not_retryable"):
        collector_health.record_transient_failure(
            "clipboard_maintenance",
            CollectorFailureCode.UNEXPECTED_FAILURE,
        )


def test_clipboard_maintenance_cannot_downgrade_unknown_failures(monkeypatch):
    def fail_prune():
        raise RuntimeError("broken retention invariant")

    monkeypatch.setattr(
        collector_module.clipboard_service,
        "prune_old_events",
        fail_prune,
    )

    with pytest.raises(ValueError, match="collector_failure_code_not_retryable"):
        collector_module._run_clipboard_maintenance_tick()


def test_clipboard_maintenance_records_controlled_contention(monkeypatch):
    captured: list[tuple[str, CollectorFailureCode]] = []

    def fail_prune():
        raise sqlite3.OperationalError("database is locked")

    def capture_failure(
        phase: str,
        code: CollectorFailureCode,
        _at_time: str | None = None,
    ) -> None:
        captured.append((phase, code))

    monkeypatch.setattr(
        collector_module.clipboard_service,
        "prune_old_events",
        fail_prune,
    )
    monkeypatch.setattr(
        collector_module.collector_health,
        "record_transient_failure",
        capture_failure,
    )

    collector_module._run_clipboard_maintenance_tick()
    assert captured == [
        ("clipboard_maintenance", CollectorFailureCode.DATABASE_BUSY)
    ]


def test_collector_health_never_receives_or_classifies_raw_failures():
    health_source = (
        ROOT / "worktrace/collector/collector_health.py"
    ).read_text(encoding="utf-8")
    collector_source = (
        ROOT / "worktrace/collector/collector.py"
    ).read_text(encoding="utf-8")

    assert "BaseException" not in health_source
    assert "sqlite3" not in health_source
    assert "CollectorFailureCode | str" not in health_source
    assert "is_transient_failure" not in health_source
    assert "classify_collector_failure" not in health_source
    assert "classify_collector_failure" in collector_source
    assert "is_transient_failure" not in collector_source
    assert "record_transient_failure(phase, exc" not in collector_source
    assert "record_fatal_failure(phase, exc" not in collector_source
    assert "type(exc).__name__" not in collector_source
