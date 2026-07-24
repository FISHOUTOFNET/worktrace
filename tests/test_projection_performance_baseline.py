"""Projection performance baseline and instrumentation contract tests.

These tests do two jobs:
  * Verify the performance instrumentation captures the expected stages and
    counts without asserting on fragile absolute timings.
  * Produce a reproducible benchmark dataset at 100/500/1000/2000 activities
    so subsequent phases can compare before/after behaviour against the same
    fixture. The benchmark is marked ``slow`` so it does not run in the
    default fast loop.

The benchmark records ``uncached`` projection, ``cached`` projection (within
the same page-read scope), and ``detail_lookup`` durations as captured by
:mod:`worktrace.services.projection_performance`. Absolute thresholds are
intentionally loose; the hard acceptance gates live in later phases.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from tests.support import projection_benchmark
from worktrace.services import (
    projection_performance,
    report_projection_snapshot_service,
    view_model_service,
)
from worktrace.services.page_read_context import page_read_scope
from worktrace.services.projection_performance import projection_perf_scope

pytestmark = [pytest.mark.db, pytest.mark.slow, pytest.mark.serial]

BENCHMARK_SIZES = (100, 500, 1000, 2000)


def _reset_perf_capture():
    projection_performance.reset_last_record()


def _last_record_or_fail():
    record = projection_performance.get_last_record()
    assert record is not None, "projection_perf_scope did not capture a record"
    return record


@contextmanager
def _perf_page_scope(report_date: str, *, surface: str = "test"):
    """Bind a perf scope around a page-read scope for direct service calls.

    In production the API layer binds the perf scope. Tests that call the
    projection service directly must bind the scope themselves so the
    ``stage`` calls inside the service accumulate on a record.
    """

    with projection_perf_scope(report_date, surface=surface):
        with page_read_scope():
            yield


def test_perf_scope_captures_stage_durations(temp_db):
    _reset_perf_capture()
    projection_benchmark.build_benchmark_dataset(activity_count=20)
    with _perf_page_scope(projection_benchmark.DEFAULT_REPORT_DATE):
        report_projection_snapshot_service.build_visible_snapshot(
            projection_benchmark.DEFAULT_REPORT_DATE,
            projection_benchmark.DEFAULT_REPORT_DATE,
        )
    record = _last_record_or_fail()
    assert record.report_date == projection_benchmark.DEFAULT_REPORT_DATE
    # Core stages must be present. Exact durations are machine-dependent.
    for required in (
        "fact_query",
        "session_build",
        "operation_load",
        "operation_replay",
        "snapshot_finalize",
        "snapshot_hash",
    ):
        assert required in record.stages, f"missing stage {required}"
    assert record.activity_count >= 20
    assert record.entry_count >= 1
    assert record.contribution_count >= 1
    assert record.total_ms > 0.0


def test_perf_scope_does_not_log_fast_requests(temp_db, caplog):
    _reset_perf_capture()
    projection_benchmark.build_benchmark_dataset(activity_count=5)
    projection_performance.set_threshold_ms(10_000.0)
    try:
        with caplog.at_level(
            "WARNING", logger="worktrace.projection_perf"
        ):
            with _perf_page_scope(projection_benchmark.DEFAULT_REPORT_DATE):
                report_projection_snapshot_service.build_visible_snapshot(
                    projection_benchmark.DEFAULT_REPORT_DATE,
                    projection_benchmark.DEFAULT_REPORT_DATE,
                )
        assert not any(
            "projection_perf_slow" in record.message for record in caplog.records
        )
    finally:
        projection_performance.set_threshold_ms(
            projection_performance._DEFAULT_THRESHOLD_MS
        )


def test_perf_scope_logs_slow_requests(temp_db, caplog):
    _reset_perf_capture()
    projection_benchmark.build_benchmark_dataset(activity_count=5)
    projection_performance.set_threshold_ms(0.0)
    try:
        with caplog.at_level(
            "WARNING", logger="worktrace.projection_perf"
        ):
            with _perf_page_scope(projection_benchmark.DEFAULT_REPORT_DATE):
                report_projection_snapshot_service.build_visible_snapshot(
                    projection_benchmark.DEFAULT_REPORT_DATE,
                    projection_benchmark.DEFAULT_REPORT_DATE,
                )
        assert any(
            "projection_perf_slow" in record.message for record in caplog.records
        )
    finally:
        projection_performance.set_threshold_ms(
            projection_performance._DEFAULT_THRESHOLD_MS
        )


def test_perf_scope_records_cache_hit_for_page_context(temp_db):
    _reset_perf_capture()
    projection_benchmark.build_benchmark_dataset(activity_count=10)
    with _perf_page_scope(projection_benchmark.DEFAULT_REPORT_DATE):
        first = report_projection_snapshot_service.build_visible_snapshot(
            projection_benchmark.DEFAULT_REPORT_DATE,
            projection_benchmark.DEFAULT_REPORT_DATE,
        )
        second = report_projection_snapshot_service.build_visible_snapshot(
            projection_benchmark.DEFAULT_REPORT_DATE,
            projection_benchmark.DEFAULT_REPORT_DATE,
        )
    assert first is second
    record = _last_record_or_fail()
    assert record.cache_hit is True


def test_perf_scope_does_not_log_privacy_data(temp_db, caplog):
    _reset_perf_capture()
    projection_benchmark.build_benchmark_dataset(activity_count=10)
    projection_performance.set_threshold_ms(0.0)
    try:
        with caplog.at_level(
            "WARNING", logger="worktrace.projection_perf"
        ):
            with _perf_page_scope(projection_benchmark.DEFAULT_REPORT_DATE):
                report_projection_snapshot_service.build_visible_snapshot(
                    projection_benchmark.DEFAULT_REPORT_DATE,
                    projection_benchmark.DEFAULT_REPORT_DATE,
                )
        messages = [record.message for record in caplog.records]
        for forbidden in ("Doc", "App", "D:\\\\", "window_title", "path_hint"):
            assert not any(forbidden in message for message in messages), (
                f"perf log leaked {forbidden!r}: {messages}"
            )
    finally:
        projection_performance.set_threshold_ms(
            projection_performance._DEFAULT_THRESHOLD_MS
        )


@pytest.mark.parametrize("size", BENCHMARK_SIZES)
def test_projection_benchmark_baseline(temp_db, size):
    """Record before-fix projection timings for each benchmark size.

    This is a baseline benchmark, not a pass/fail gate. It asserts only that
    the projection completes and the perf record captures the expected shape.
    Absolute timings are printed via the record for human inspection.
    """

    _reset_perf_capture()
    projection_benchmark.build_benchmark_dataset(
        activity_count=size,
        seed_session_operation=True,
        seed_in_progress=True,
    )
    report_date = projection_benchmark.DEFAULT_REPORT_DATE

    # Uncached build: fresh page-read scope so the per-request snapshot cache
    # is empty.
    with _perf_page_scope(report_date):
        snapshot = report_projection_snapshot_service.build_visible_snapshot(
            report_date, report_date
        )
    uncached_record = _last_record_or_fail()
    assert uncached_record.activity_count >= size
    assert uncached_record.entry_count >= 1
    assert uncached_record.contribution_count >= 1

    # Cached build: pre-populate the request cache, then measure only the
    # cached hit inside its own perf scope so stage timings reflect a single
    # cache-hit call rather than the sum of build + hit.
    _reset_perf_capture()
    with page_read_scope():
        report_projection_snapshot_service.build_visible_snapshot(
            report_date, report_date
        )
        with projection_perf_scope(report_date, surface="cached"):
            cached = report_projection_snapshot_service.build_visible_snapshot(
                report_date, report_date
            )
    cached_record = _last_record_or_fail()
    assert cached_record.cache_hit is True

    # Detail lookup: pick the first session and request its activity summary
    # through the view model layer so the detail_lookup stage is captured.
    _reset_perf_capture()
    first_session = snapshot.final_sessions[0]
    projection_key = str(first_session.get("projection_instance_key") or "")
    projection_revision = str(first_session.get("projection_revision") or "")
    assert projection_key and projection_revision
    with _perf_page_scope(report_date):
        view_model_service.get_session_activity_summary_view_model(
            report_date=report_date,
            projection_instance_key=projection_key,
            expected_projection_revision=projection_revision,
        )
    detail_record = _last_record_or_fail()
    assert "detail_lookup" in detail_record.stages

    # Print for human inspection in CI logs (not an assertion).
    print(
        f"\n[baseline size={size}] "
        f"uncached_total_ms={uncached_record.total_ms:.2f} "
        f"fact_query_ms={uncached_record.stage_total('fact_query'):.2f} "
        f"session_build_ms={uncached_record.stage_total('session_build'):.2f} "
        f"operation_replay_ms={uncached_record.stage_total('operation_replay'):.2f} "
        f"snapshot_hash_ms={uncached_record.stage_total('snapshot_hash'):.2f} "
        f"cached_total_ms={cached_record.total_ms:.2f} "
        f"detail_total_ms={detail_record.total_ms:.2f} "
        f"detail_lookup_ms={detail_record.stage_total('detail_lookup'):.2f}"
    )


def test_timeline_view_model_records_view_model_transform_stage(temp_db):
    _reset_perf_capture()
    projection_benchmark.build_benchmark_dataset(activity_count=40)
    with _perf_page_scope(projection_benchmark.DEFAULT_REPORT_DATE):
        view_model_service.get_timeline_view_model(
            projection_benchmark.DEFAULT_REPORT_DATE
        )
    record = _last_record_or_fail()
    assert "view_model_transform" in record.stages
    assert record.entry_count >= 1


def test_detail_view_model_records_detail_lookup_stage(temp_db):
    _reset_perf_capture()
    info = projection_benchmark.build_benchmark_dataset(activity_count=30)
    # Build once to discover a projection key for the detail request.
    with _perf_page_scope(info["report_date"]):
        snapshot = report_projection_snapshot_service.build_visible_snapshot(
            info["report_date"], info["report_date"]
        )
    first_session = snapshot.final_sessions[0]
    projection_key = str(first_session.get("projection_instance_key") or "")
    projection_revision = str(first_session.get("projection_revision") or "")
    _reset_perf_capture()
    with _perf_page_scope(info["report_date"]):
        view_model_service.get_session_activity_summary_view_model(
            report_date=info["report_date"],
            projection_instance_key=projection_key,
            expected_projection_revision=projection_revision,
        )
    record = _last_record_or_fail()
    assert "detail_lookup" in record.stages
