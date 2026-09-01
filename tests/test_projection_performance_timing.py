"""Unit tests for projection performance timing semantics."""

from __future__ import annotations

import pytest

from worktrace.services import projection_performance


def _set_fake_clocks(monkeypatch, *, elapsed_values, cpu_values) -> None:
    elapsed = iter(elapsed_values)
    cpu = iter(cpu_values)
    monkeypatch.setattr(
        projection_performance.time,
        "perf_counter",
        lambda: next(elapsed),
    )
    monkeypatch.setattr(
        projection_performance.time,
        "thread_time",
        lambda: next(cpu),
    )


def test_scope_records_elapsed_and_thread_cpu_independently(monkeypatch):
    projection_performance.reset_last_record()
    _set_fake_clocks(
        monkeypatch,
        elapsed_values=(100.0, 110.0),
        cpu_values=(20.0, 20.05),
    )
    projection_performance.set_threshold_ms(100_000.0)
    try:
        with projection_performance.projection_perf_scope(
            "2026-08-31",
            surface="timing_contract",
        ):
            pass
    finally:
        projection_performance.set_threshold_ms(
            projection_performance._DEFAULT_THRESHOLD_MS
        )

    record = projection_performance.get_last_record()
    assert record is not None
    assert record.total_ms == pytest.approx(10_000.0)
    assert record.total_cpu_ms == pytest.approx(50.0)
    assert record.to_log_payload()["total_ms"] == pytest.approx(10_000.0)
    assert record.to_log_payload()["total_cpu_ms"] == pytest.approx(50.0)


def test_slow_classification_remains_elapsed_based(monkeypatch, caplog):
    projection_performance.reset_last_record()
    _set_fake_clocks(
        monkeypatch,
        elapsed_values=(100.0, 102.0),
        cpu_values=(20.0, 20.001),
    )
    projection_performance.set_threshold_ms(1_000.0)
    try:
        with caplog.at_level(
            "WARNING",
            logger="worktrace.projection_perf",
        ):
            with projection_performance.projection_perf_scope(
                "2026-08-31",
                surface="timing_contract",
            ):
                pass
    finally:
        projection_performance.set_threshold_ms(
            projection_performance._DEFAULT_THRESHOLD_MS
        )

    record = projection_performance.get_last_record()
    assert record is not None
    assert record.total_ms == pytest.approx(2_000.0)
    assert record.total_cpu_ms == pytest.approx(1.0)
    assert any(
        "projection_perf_slow" in item.message for item in caplog.records
    )
