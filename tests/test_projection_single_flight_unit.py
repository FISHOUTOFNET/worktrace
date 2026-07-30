"""Pure state-machine unit tests for the ReportProjectionProvider single-flight.

These tests verify the single-flight concurrency mechanism using barriers,
events, and fake builders — no database fixture, no page-read scope.
They run as pure unit tests so they can execute quickly in Standard CI
without the database fixture overhead.

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
* ProjectionWaitTimeout carries structured diagnostics (no privacy data).
* waiter_count returns to zero after successful build.

The tests use deterministic waiter-count polling instead of fixed timing
waits — see ``_wait_for_waiters``.
"""

from __future__ import annotations

import threading
import time

import pytest

from worktrace.services.report_projection_provider import (
    DayProjection,
    ProjectionWaitTimeout,
    _single_flight_build,
    cache_size,
    clear_cache,
    get_wait_timeout,
    get_waiter_count,
    in_flight_count,
    set_wait_timeout,
)
from worktrace.services.report_revision_service import ProjectionSourceVersion

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]

DB_KEY = "test_db"
DATE_A = "2026-07-20"
DATE_B = "2026-07-21"


def _wait_for_waiters(
    database_key: str,
    report_date: str,
    source_version_token: str,
    expected_count: int,
    *,
    timeout: float = 5.0,
) -> None:
    """Poll get_waiter_count until it reaches ``expected_count``.

    Deterministic replacement for _brief_settle: no fixed timing waits,
    just polls until all waiters have joined the in-flight Future.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        count = get_waiter_count(
            database_key, report_date, source_version_token
        )
        if count >= expected_count:
            return
        threading.Event().wait(0.005)
    raise TimeoutError(
        f"waiter count did not reach {expected_count} within {timeout}s"
    )


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


def test_twenty_threads_same_date_single_build():
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
    # Wait until all 19 waiters have joined the in-flight Future.
    # The builder is blocked on build_can_finish so the in-flight entry
    # cannot be cleaned up yet — no thread can miss the join window.
    _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 19)
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


def test_builder_exception_propagates_to_all_waiters():
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
    # Wait until all 4 waiters have joined the in-flight Future.
    # The builder is blocked on build_can_fail so the in-flight entry
    # cannot be cleaned up yet.
    _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 4)
    # Let the builder fail — all waiters should receive the exception.
    build_can_fail.set()
    for t in threads:
        t.join(timeout=10)

    assert build_count == 1
    for e in errors:
        assert isinstance(e, RuntimeError), f"expected RuntimeError, got {type(e).__name__}: {e}"
        assert str(e) == "build_failed"
    assert in_flight_count() == 0


def test_rebuild_after_exception_succeeds():
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


def test_clear_during_build_prevents_cache_publish():
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


def test_clear_during_build_new_request_does_not_wait():
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


def test_different_dates_build_in_parallel():
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


def test_wait_timeout_raises_projection_wait_timeout():
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


def test_timeout_does_not_remove_inflight_for_other_waiters():
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


def test_inflight_empty_after_successful_build():
    sv = _make_source_version(DATE_A)
    _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
    assert in_flight_count() == 0


def test_inflight_empty_after_exception():
    sv = _make_source_version(DATE_A)

    def fail():
        raise ValueError("fail")

    with pytest.raises(ValueError):
        _single_flight_build(DB_KEY, DATE_A, sv, fail)
    assert in_flight_count() == 0


# --- Diagnostic fields on ProjectionWaitTimeout ---


def test_timeout_exception_carries_diagnostics():
    """ProjectionWaitTimeout must carry report_date, epoch, waiter_count, etc.

    Privacy: the exception must NOT carry window titles, paths, or
    project names — only structured diagnostic fields.
    """
    sv = _make_source_version(DATE_A)
    set_wait_timeout(0.1)
    build_started = threading.Event()
    build_can_finish = threading.Event()

    def builder():
        build_started.set()
        build_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    builder_thread = threading.Thread(
        target=lambda: _single_flight_build(DB_KEY, DATE_A, sv, builder)
    )
    builder_thread.start()
    assert build_started.wait(timeout=5)

    timeout_error: list[BaseException | None] = [None]
    try:
        _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
    except BaseException as exc:
        timeout_error[0] = exc

    assert isinstance(timeout_error[0], ProjectionWaitTimeout)
    exc = timeout_error[0]
    assert exc.report_date == DATE_A
    assert exc.source_version_token == sv.token()
    assert exc.timeout_seconds == 0.1
    assert exc.builder_elapsed_seconds >= 0.0
    assert exc.waiter_count >= 0
    assert exc.total_in_flight_count >= 1
    # No privacy-sensitive data in the exception message.
    message = str(exc)
    for forbidden in ("window_title", "path_hint", "project_name", "Doc"):
        assert forbidden not in message, (
            f"ProjectionWaitTimeout message leaked {forbidden!r}: {message}"
        )

    build_can_finish.set()
    builder_thread.join(timeout=5)
    assert in_flight_count() == 0


def test_waiter_count_returns_to_zero_after_successful_build():
    """After a successful build with waiters, waiter_count must be 0."""
    sv = _make_source_version(DATE_A)
    build_started = threading.Event()
    build_can_finish = threading.Event()

    def builder():
        build_started.set()
        build_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    results: list[DayProjection | None] = [None] * 3

    def worker(idx: int):
        results[idx] = _single_flight_build(DB_KEY, DATE_A, sv, builder)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    threads[0].start()  # becomes builder
    assert build_started.wait(timeout=5)
    threads[1].start()  # waiter 1
    threads[2].start()  # waiter 2
    _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 2)
    assert get_waiter_count(DB_KEY, DATE_A, sv.token()) == 2

    build_can_finish.set()
    for t in threads:
        t.join(timeout=5)

    assert all(r is not None for r in results)
    assert results[0] is results[1] is results[2]
    assert get_waiter_count(DB_KEY, DATE_A, sv.token()) == 0
    assert in_flight_count() == 0


# --- Scenario A: two waiters, one times out, intermediate counts correct ---


def test_two_waiters_one_timeout_intermediate_counts_correct():
    """Scenario A: waiter A times out while waiter B still waits.

    Sequence:
      1. owner enters computation (blocked);
      2. waiter A registers (short timeout) → count == 1;
      3. waiter B registers (long timeout) → count == 2;
      4. waiter A times out;
      5. after waiter A exits, waiter B is still waiting → count == 1;
      6. owner completes;
      7. waiter B gets the result;
      8. final count == 0, no underflow, no erroneous cleanup.

    Uses staggered timeouts: waiter A gets a short timeout so it fires
    while waiter B (with a long timeout) is still waiting.  The global
    ``_PROJECTION_WAIT_TIMEOUT`` is read at ``future.result()`` call
    time, so changing it between waiter starts gives each waiter a
    different deadline.
    """
    sv = _make_source_version(DATE_A)
    build_started = threading.Event()
    build_can_finish = threading.Event()

    def builder():
        build_started.set()
        build_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    builder_error: list[BaseException | None] = [None]

    def builder_thread_fn():
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, builder)
        except BaseException as exc:
            builder_error[0] = exc

    builder_thread = threading.Thread(target=builder_thread_fn)
    builder_thread.start()
    assert build_started.wait(timeout=5)

    # Waiter A — short timeout, will time out.
    set_wait_timeout(0.3)
    waiter_a_result: list[BaseException | None] = [None]
    waiter_a_done = threading.Event()

    def waiter_a():
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
        except BaseException as exc:
            waiter_a_result[0] = exc
        finally:
            waiter_a_done.set()

    t_a = threading.Thread(target=waiter_a)
    t_a.start()
    _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 1)

    # Waiter B — long timeout, should still be waiting when A times out.
    set_wait_timeout(30.0)
    waiter_b_result: list[DayProjection | None] = [None]
    waiter_b_error: list[BaseException | None] = [None]
    waiter_b_done = threading.Event()

    def waiter_b():
        try:
            waiter_b_result[0] = _single_flight_build(
                DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A)
            )
        except BaseException as exc:
            waiter_b_error[0] = exc
        finally:
            waiter_b_done.set()

    t_b = threading.Thread(target=waiter_b)
    t_b.start()
    _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 2)
    assert get_waiter_count(DB_KEY, DATE_A, sv.token()) == 2

    # Waiter A times out (short timeout).
    assert waiter_a_done.wait(timeout=5), "waiter A did not exit"
    assert isinstance(waiter_a_result[0], ProjectionWaitTimeout)

    # After waiter A exits, waiter B is still waiting → count == 1.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if get_waiter_count(DB_KEY, DATE_A, sv.token()) == 1:
            break
        threading.Event().wait(0.01)
    assert get_waiter_count(DB_KEY, DATE_A, sv.token()) == 1, (
        "waiter B should still be waiting after waiter A timed out"
    )
    assert not waiter_b_done.is_set(), "waiter B should still be blocked"

    # Owner completes → waiter B gets the result.
    build_can_finish.set()
    builder_thread.join(timeout=5)
    assert builder_error[0] is None, f"builder got error: {builder_error[0]}"
    assert waiter_b_done.wait(timeout=5), "waiter B did not complete"

    assert waiter_b_error[0] is None, f"waiter B got error: {waiter_b_error[0]}"
    assert waiter_b_result[0] is not None
    assert waiter_b_result[0].snapshot_revision == "rev-" + DATE_A

    t_a.join(timeout=5)
    t_b.join(timeout=5)

    assert get_waiter_count(DB_KEY, DATE_A, sv.token()) == 0
    assert in_flight_count() == 0


# --- Scenario B: timeout diagnostic snapshot includes timing-out waiter ---


def test_timeout_diagnostic_snapshot_includes_timing_out_waiter():
    """Scenario B: the waiter_count in the timeout diagnostic is read
    BEFORE the decrement and includes the timing-out waiter.

    Semantics: ``waiter_count`` in :class:`ProjectionWaitTimeout` counts
    all waiters that had joined at the moment of the timeout, including
    the one that is timing out.  This is consistent with the code: the
    snapshot is taken before the single ``finally`` decrement.

    Uses staggered timeouts so waiter A times out first while waiter B
    is still waiting.  Waiter A's snapshot should then show count == 2.
    """
    sv = _make_source_version(DATE_A)
    build_started = threading.Event()
    build_can_finish = threading.Event()

    def builder():
        build_started.set()
        build_can_finish.wait(timeout=5)
        return _fake_projection(DATE_A)

    builder_error: list[BaseException | None] = [None]

    def builder_thread_fn():
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, builder)
        except BaseException as exc:
            builder_error[0] = exc

    builder_thread = threading.Thread(target=builder_thread_fn)
    builder_thread.start()
    assert build_started.wait(timeout=5)

    # Waiter A — short timeout, will time out first.
    set_wait_timeout(0.3)
    waiter_a_error: list[BaseException | None] = [None]
    waiter_a_done = threading.Event()

    def waiter_a():
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
        except BaseException as exc:
            waiter_a_error[0] = exc
        finally:
            waiter_a_done.set()

    t_a = threading.Thread(target=waiter_a)
    t_a.start()
    _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 1)

    # Waiter B — long timeout, still waiting when A times out.
    set_wait_timeout(30.0)
    waiter_b_error: list[BaseException | None] = [None]
    waiter_b_done = threading.Event()

    def waiter_b():
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
        except BaseException as exc:
            waiter_b_error[0] = exc
        finally:
            waiter_b_done.set()

    t_b = threading.Thread(target=waiter_b)
    t_b.start()
    _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 2)

    # Waiter A times out first (short timeout).
    assert waiter_a_done.wait(timeout=5), "waiter A did not time out"
    assert isinstance(waiter_a_error[0], ProjectionWaitTimeout)

    # The snapshot was taken before the decrement, so it includes the
    # timing-out waiter A → count must be 2 (both waiters joined).
    assert waiter_a_error[0].waiter_count == 2, (
        f"expected snapshot waiter_count==2 (includes timing-out waiter), "
        f"got {waiter_a_error[0].waiter_count}"
    )

    # Waiter B should still be waiting.
    assert not waiter_b_done.is_set(), "waiter B should still be blocked"

    build_can_finish.set()
    builder_thread.join(timeout=5)
    assert builder_error[0] is None, f"builder got error: {builder_error[0]}"
    assert waiter_b_done.wait(timeout=5), "waiter B did not complete"
    assert waiter_b_error[0] is None, f"waiter B got error: {waiter_b_error[0]}"

    t_a.join(timeout=5)
    t_b.join(timeout=5)
    assert in_flight_count() == 0


# --- Scenario C: owner exception, two waiters, each exits once ---


def test_owner_exception_two_waiters_single_exit_no_underflow():
    """Scenario C: owner raises, both waiters receive the exception,
    each waiter exits exactly once, and waiter_count returns to 0
    without going negative.
    """
    sv = _make_source_version(DATE_A)
    build_started = threading.Event()
    build_can_fail = threading.Event()

    def builder():
        build_started.set()
        build_can_fail.wait(timeout=5)
        raise RuntimeError("owner_build_failed")

    builder_error: list[BaseException | None] = [None]

    def builder_thread_fn():
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, builder)
        except BaseException as exc:
            builder_error[0] = exc

    builder_thread = threading.Thread(target=builder_thread_fn)
    builder_thread.start()
    assert build_started.wait(timeout=5)

    errors: list[BaseException | None] = [None, None]
    done_count = {"count": 0}
    done_lock = threading.Lock()

    def waiter(idx: int):
        try:
            _single_flight_build(DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A))
        except BaseException as exc:
            errors[idx] = exc
        finally:
            with done_lock:
                done_count["count"] += 1

    t0 = threading.Thread(target=waiter, args=(0,))
    t1 = threading.Thread(target=waiter, args=(1,))
    t0.start()
    t1.start()
    _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 2)
    assert get_waiter_count(DB_KEY, DATE_A, sv.token()) == 2

    build_can_fail.set()
    builder_thread.join(timeout=5)
    t0.join(timeout=5)
    t1.join(timeout=5)

    # Builder received its own exception (expected).
    assert isinstance(builder_error[0], RuntimeError)

    # Both waiters received the owner's exception.
    for i, exc in enumerate(errors):
        assert isinstance(exc, RuntimeError), (
            f"waiter {i} expected RuntimeError, got {type(exc).__name__}: {exc}"
        )
        assert str(exc) == "owner_build_failed"

    # Each waiter exited exactly once.
    assert done_count["count"] == 2

    # No underflow — count back to 0.
    assert get_waiter_count(DB_KEY, DATE_A, sv.token()) == 0
    assert in_flight_count() == 0


# --- Scenario D: owner completion vs timeout race ---


def test_owner_completion_vs_timeout_race_state_closes():
    """Scenario D: owner completes near the timeout boundary.

    Regardless of whether the waiter sees success or timeout, the state
    must close cleanly: no double decrement, no double in-flight removal,
    no invalid state.  Run the race multiple times to exercise both
    branches.
    """
    sv = _make_source_version(DATE_A)
    set_wait_timeout(0.15)

    for iteration in range(8):
        clear_cache()
        build_started = threading.Event()
        build_can_finish = threading.Event()

        def builder():
            build_started.set()
            build_can_finish.wait(timeout=5)
            return _fake_projection(DATE_A)

        builder_error: list[BaseException | None] = [None]

        def builder_thread_fn():
            try:
                _single_flight_build(DB_KEY, DATE_A, sv, builder)
            except BaseException as exc:
                builder_error[0] = exc

        builder_thread = threading.Thread(target=builder_thread_fn)
        builder_thread.start()
        assert build_started.wait(timeout=5)

        waiter_error: list[BaseException | None] = [None]
        waiter_result: list[DayProjection | None] = [None]
        waiter_done = threading.Event()

        def waiter():
            try:
                waiter_result[0] = _single_flight_build(
                    DB_KEY, DATE_A, sv, lambda: _fake_projection(DATE_A)
                )
            except BaseException as exc:
                waiter_error[0] = exc
            finally:
                waiter_done.set()

        t = threading.Thread(target=waiter)
        t.start()
        # Wait for the waiter to join the in-flight Future.
        _wait_for_waiters(DB_KEY, DATE_A, sv.token(), 1)

        # Release the builder near the timeout boundary.  The waiter
        # either gets the result (success) or times out — both are
        # valid.  The invariant is that the state closes cleanly.
        build_can_finish.set()
        builder_thread.join(timeout=5)
        assert builder_error[0] is None, f"builder got error: {builder_error[0]}"
        assert waiter_done.wait(timeout=5), "waiter did not exit"

        t.join(timeout=5)

        # Either success or ProjectionWaitTimeout is acceptable.
        if waiter_error[0] is not None:
            assert isinstance(waiter_error[0], ProjectionWaitTimeout), (
                f"unexpected error: {waiter_error[0]}"
            )
        else:
            assert waiter_result[0] is not None

        # State must close: no leaked in-flight entry, no negative count.
        assert in_flight_count() == 0, (
            f"iteration {iteration}: in_flight_count={in_flight_count()}"
        )
        assert get_waiter_count(DB_KEY, DATE_A, sv.token()) == 0
