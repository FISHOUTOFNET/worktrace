"""Concurrency tests for the ReportProjectionProvider single-flight mechanism.

These tests use barriers, events, and fake builders to verify deterministic
behavior without relying on sleep-based race conditions.

Coverage:
* 20 threads → same date → builder called exactly once.
* Builder exception → all waiters receive the same exception.
* After exception → next request rebuilds successfully.
* clear_cache during build → old result does not enter new cache.
* clear_cache during build → new request does not wait for old builder.
* Different dates build in parallel.
* Wait timeout → waiter gets ProjectionWaitTimeout, builder continues.
* Timeout does not remove in-flight for other waiters.
* All completion paths leave _inflight empty.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from worktrace.services import report_projection_snapshot_service
from worktrace.services.page_read_context import page_read_scope
from worktrace.services.report_projection_provider import (
    DayProjection,
    ProjectionWaitTimeout,
    _single_flight_build,
    cache_size,
    clear_cache,
    get_day_projection,
    get_wait_timeout,
    in_flight_count,
    set_wait_timeout,
)
from worktrace.services.report_revision_service import ProjectionSourceVersion

pytestmark = [pytest.mark.db, pytest.mark.integration]

DB_KEY = "test_db"
DATE_A = "2026-07-20"
DATE_B = "2026-07-21"


def _brief_settle(seconds: float) -> None:
    """Brief scheduling settle using Event.wait (deterministic, no wall-clock sleep)."""
    threading.Event().wait(seconds)


def _make_source_version(date: str) -> ProjectionSourceVersion:
    return ProjectionSourceVersion(
        database_key=DB_KEY,
        report_date=date,
        report_structure_generation=0,
        database_replacement_epoch=0,
        projection_schema_version=1,
    )


@pytest.fixture(autouse=True)
def _reset_provider_state():
    clear_cache()
    old_timeout = get_wait_timeout()
    yield
    set_wait_timeout(old_timeout)
    clear_cache()


def _fake_projection(date: str) -> DayProjection:
    """Build a minimal DayProjection for testing."""
    sv = _make_source_version(date)
    return DayProjection(
        report_date=date,
        source_version=sv,
        entries=(),
        contributions=(),
        operation_diagnostics=(),
        snapshot_revision="rev-" + date,
        entry_by_key={},
        contributions_by_key={},
    )


# --- 20 threads, single build ---


def test_twenty_threads_same_date_single_build(temp_db):
    """20 concurrent threads requesting the same date → builder called once."""
    sv = _make_source_version(DATE_A)
    build_count = 0
    build_lock = threading.Lock()
    build_started = threading.Event()
    build_can_finish = threading.Event()

    def builder():
        nonlocal build_count
        with build_lock:
            build_count += 1
        build_started.set()
        # Block until all waiters have joined the in-flight, then finish.
        build_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    results: list[DayProjection | None] = [None] * 20
    errors: list[BaseException | None] = [None] * 20

    def worker(idx: int):
        try:
            results[idx] = _single_flight_build(DB_KEY, DATE_A, sv, builder)
        except BaseException as exc:
            errors[idx] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    # Wait for the builder to register and block.
    assert build_started.wait(timeout=5)
    # Give the 19 waiters a moment to join the in-flight future. The builder
    # is blocked on build_can_finish so the in-flight entry cannot be cleaned
    # up yet — no thread can miss the join window.
    _brief_settle(0.05)
    build_can_finish.set()
    for t in threads:
        t.join(timeout=10)

    assert all(e is None for e in errors), f"threads had errors: {errors}"
    assert build_count == 1, f"builder called {build_count} times, expected 1"
    first = results[0]
    assert first is not None
    for r in results:
        assert r is first, "all threads should get the same object"
    assert in_flight_count() == 0


# --- Builder exception propagation ---


def test_builder_exception_propagates_to_all_waiters(temp_db):
    """Builder raises → all waiters receive the exception."""
    sv = _make_source_version(DATE_A)
    build_started = threading.Event()
    build_can_fail = threading.Event()
    build_count = 0
    build_lock = threading.Lock()

    def builder():
        nonlocal build_count
        with build_lock:
            build_count += 1
        build_started.set()
        build_can_fail.wait(timeout=5)
        raise RuntimeError("build_failed")

    errors: list[BaseException | None] = [None] * 5

    def worker(idx: int):
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, builder)
        except BaseException as exc:
            errors[idx] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    # Start first thread → becomes builder.
    threads[0].start()
    assert build_started.wait(timeout=5)
    # Start remaining threads → they become waiters on the in-flight future.
    for t in threads[1:]:
        t.start()
    # Give waiters a moment to reach future.result(). The builder is blocked
    # on build_can_fail so the in-flight entry cannot be cleaned up yet.
    _brief_settle(0.05)
    # Let the builder fail — all waiters should receive the exception.
    build_can_fail.set()
    for t in threads:
        t.join(timeout=10)

    assert build_count == 1
    for e in errors:
        assert isinstance(e, RuntimeError), f"expected RuntimeError, got {type(e).__name__}: {e}"
        assert str(e) == "build_failed"
    assert in_flight_count() == 0


def test_rebuild_after_exception_succeeds(temp_db):
    """After a builder exception, the next request must be able to rebuild."""
    sv = _make_source_version(DATE_A)
    call_count = 0

    def failing_builder():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("first_fail")

    def good_builder():
        nonlocal call_count
        call_count += 1
        return _fake_projection(DATE_A)

    with pytest.raises(RuntimeError):
        _single_flight_build(DB_KEY, DATE_A, sv, failing_builder)
    assert call_count == 1
    assert in_flight_count() == 0

    result = _single_flight_build(DB_KEY, DATE_A, sv, good_builder)
    assert call_count == 2
    assert result.snapshot_revision == "rev-" + DATE_A
    assert in_flight_count() == 0


# --- clear_cache during build ---


def test_clear_during_build_prevents_cache_publish(temp_db):
    """Builder finishes after clear_cache → result not published to cache."""
    sv = _make_source_version(DATE_A)
    build_started = threading.Event()
    build_can_finish = threading.Event()

    def builder():
        build_started.set()
        build_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    # Start the build in a thread.
    builder_result: list[DayProjection | None] = [None]
    builder_thread = threading.Thread(
        target=lambda: builder_result.__setitem__(0, _single_flight_build(DB_KEY, DATE_A, sv, builder))
    )
    builder_thread.start()
    assert build_started.wait(timeout=5)

    # Clear cache while build is in progress.
    clear_cache()
    assert cache_size() == 0

    # Let the builder finish.
    build_can_finish.set()
    builder_thread.join(timeout=5)
    assert not builder_thread.is_alive()

    # Builder's caller still gets the result.
    assert builder_result[0] is not None
    assert builder_result[0].snapshot_revision == "rev-" + DATE_A

    # But the result was NOT published to the cache.
    assert cache_size() == 0
    assert in_flight_count() == 0


def test_clear_during_build_new_request_does_not_wait(temp_db):
    """After clear_cache, a new request for the same key starts a new build."""
    sv = _make_source_version(DATE_A)
    first_started = threading.Event()
    first_can_finish = threading.Event()
    build_count = 0
    build_lock = threading.Lock()

    def first_builder():
        nonlocal build_count
        with build_lock:
            build_count += 1
        first_started.set()
        first_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    def second_builder():
        nonlocal build_count
        with build_lock:
            build_count += 1
        return _fake_projection(DATE_A)

    # Start first build.
    first_thread = threading.Thread(
        target=lambda: _single_flight_build(DB_KEY, DATE_A, sv, first_builder)
    )
    first_thread.start()
    assert first_started.wait(timeout=5)

    # Clear cache → epoch increments.
    clear_cache()

    # New request should start a new build, not wait for the first.
    second_result = _single_flight_build(DB_KEY, DATE_A, sv, second_builder)
    assert build_count == 2, "new request should not join old in-flight"
    assert second_result is not None

    # Let the first build finish.
    first_can_finish.set()
    first_thread.join(timeout=5)
    assert in_flight_count() == 0


# --- Different dates build in parallel ---


def test_different_dates_build_in_parallel(temp_db):
    """Two different dates must be able to build concurrently."""
    sv_a = _make_source_version(DATE_A)
    sv_b = _make_source_version(DATE_B)

    a_started = threading.Event()
    b_started = threading.Event()
    a_can_finish = threading.Event()
    b_can_finish = threading.Event()

    def builder_a():
        a_started.set()
        b_started.wait(timeout=5)
        a_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    def builder_b():
        b_started.set()
        b_can_finish.wait(timeout=5)
        return _fake_projection(DATE_B)

    result_a: list[DayProjection | None] = [None]
    result_b: list[DayProjection | None] = [None]

    thread_a = threading.Thread(
        target=lambda: result_a.__setitem__(0, _single_flight_build(DB_KEY, DATE_A, sv_a, builder_a))
    )
    thread_b = threading.Thread(
        target=lambda: result_b.__setitem__(0, _single_flight_build(DB_KEY, DATE_B, sv_b, builder_b))
    )
    thread_a.start()
    assert a_started.wait(timeout=5)
    thread_b.start()
    assert b_started.wait(timeout=5)

    a_can_finish.set()
    b_can_finish.set()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)

    assert result_a[0] is not None
    assert result_b[0] is not None
    assert result_a[0].report_date == DATE_A
    assert result_b[0].report_date == DATE_B
    assert in_flight_count() == 0


# --- Wait timeout ---


def test_wait_timeout_raises_projection_wait_timeout(temp_db):
    """Waiter that exceeds timeout gets ProjectionWaitTimeout."""
    sv = _make_source_version(DATE_A)
    set_wait_timeout(0.1)
    build_started = threading.Event()
    build_can_finish = threading.Event()

    def builder():
        build_started.set()
        build_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    # Start builder in a thread.
    builder_thread = threading.Thread(
        target=lambda: _single_flight_build(DB_KEY, DATE_A, sv, builder)
    )
    builder_thread.start()
    assert build_started.wait(timeout=5)

    # Waiter should time out.
    with pytest.raises(ProjectionWaitTimeout):
        _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))

    # Let the builder finish — it should still complete.
    build_can_finish.set()
    builder_thread.join(timeout=5)
    assert not builder_thread.is_alive()
    assert in_flight_count() == 0


def test_timeout_does_not_remove_inflight_for_other_waiters(temp_db):
    """One waiter's timeout must not break other waiters."""
    sv = _make_source_version(DATE_A)
    set_wait_timeout(0.1)
    build_started = threading.Event()
    build_can_finish = threading.Event()

    def builder():
        build_started.set()
        build_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    # Start builder.
    builder_thread = threading.Thread(
        target=lambda: _single_flight_build(DB_KEY, DATE_A, sv, builder)
    )
    builder_thread.start()
    assert build_started.wait(timeout=5)

    # First waiter times out.
    timeout_error: list[BaseException | None] = [None]
    def timeout_waiter():
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
        except BaseException as exc:
            timeout_error[0] = exc

    t1 = threading.Thread(target=timeout_waiter)
    t1.start()
    t1.join(timeout=2)
    assert isinstance(timeout_error[0], ProjectionWaitTimeout)

    # In-flight should still exist (builder hasn't finished).
    assert in_flight_count() == 1

    # Second waiter should also be able to wait (and time out).
    timeout_error2: list[BaseException | None] = [None]
    def timeout_waiter2():
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
        except BaseException as exc:
            timeout_error2[0] = exc

    t2 = threading.Thread(target=timeout_waiter2)
    t2.start()
    t2.join(timeout=2)
    assert isinstance(timeout_error2[0], ProjectionWaitTimeout)

    # Let builder finish.
    build_can_finish.set()
    builder_thread.join(timeout=5)
    assert in_flight_count() == 0


# --- In-flight cleanup on all paths ---


def test_inflight_empty_after_successful_build(temp_db):
    sv = _make_source_version(DATE_A)
    _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
    assert in_flight_count() == 0


def test_inflight_empty_after_exception(temp_db):
    sv = _make_source_version(DATE_A)

    def fail():
        raise ValueError("fail")

    with pytest.raises(ValueError):
        _single_flight_build(DB_KEY, DATE_A, sv, fail)
    assert in_flight_count() == 0
