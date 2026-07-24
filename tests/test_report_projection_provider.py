"""Tests for the ReportProjectionProvider: cache, single-flight, transaction bypass.

These tests verify the architectural invariants required by the projection
provider task:

* First Timeline open builds the projection exactly once.
* 20 consecutive detail clicks do NOT rebuild the day projection.
* Cache holds at most 3 date slots (LRU eviction).
* Source-version mismatch invalidates stale cache entries.
* Mutation transactions bypass the cross-request cache.
* Transaction rollback does not pollute the cache.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from tests.support import activity_factory, projection_benchmark
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection, now_str
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.services import (
    report_projection_snapshot_service,
    view_model_service,
)
from worktrace.services.page_read_context import page_read_scope
from worktrace.services.report_projection_provider import (
    DayProjection,
    cached_dates,
    cache_size,
    clear_cache,
    get_day_projection,
)
from worktrace.services.report_projection_snapshot_service import (
    build_visible_snapshot,
)

pytestmark = [pytest.mark.db, pytest.mark.integration]

DATE = "2026-07-15"


def _seed_activities(report_date: str = DATE, count: int = 5) -> None:
    for i in range(count):
        activity_factory.create_closed_activity(
            day=report_date,
            start=f"09:{i:02d}:00",
            end=f"09:{i:02d}:30",
            window_title=f"Doc{i}",
        )


@pytest.fixture(autouse=True)
def _clear_projection_cache():
    clear_cache()
    yield
    clear_cache()


def test_first_timeline_open_builds_projection_once(temp_db):
    _seed_activities()
    build_calls = []
    original = report_projection_snapshot_service._build_snapshot

    def tracking_build(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    with patch(
        "worktrace.services.report_projection_provider._build_snapshot",
        side_effect=tracking_build,
    ):
        with page_read_scope():
            proj1 = get_day_projection(DATE)
        assert len(build_calls) == 1

        # Second call in a new scope should hit cross-request cache.
        with page_read_scope():
            proj2 = get_day_projection(DATE)
        assert len(build_calls) == 1, "cross-request cache miss caused rebuild"
        assert proj2 is proj1


def test_consecutive_detail_clicks_do_not_rebuild(temp_db):
    """20 consecutive detail clicks must not trigger a day projection rebuild."""
    _seed_activities(count=10)
    clear_cache()

    # Build the projection once via the timeline path.
    with page_read_scope():
        projection = get_day_projection(DATE)
        assert len(projection.entries) >= 1

    # Simulate 20 detail clicks in separate page-read scopes.
    build_calls = []
    original = report_projection_snapshot_service._build_snapshot

    def tracking_build(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    sessions = projection.final_sessions
    assert len(sessions) >= 1
    key = str(sessions[0].get("projection_instance_key") or "")
    revision = str(sessions[0].get("projection_revision") or "")

    with patch(
        "worktrace.services.report_projection_provider._build_snapshot",
        side_effect=tracking_build,
    ):
        for _ in range(20):
            with page_read_scope():
                view_model_service.get_session_activity_summary_view_model(
                    report_date=DATE,
                    projection_instance_key=key,
                    expected_projection_revision=revision,
                )

    assert len(build_calls) == 0, (
        f"detail clicks triggered {len(build_calls)} projection rebuilds"
    )


def test_cache_evicts_at_three_slots(temp_db):
    """Cache must hold at most 3 date slots."""
    for day_offset in range(5):
        day = f"2026-07-{10 + day_offset:02d}"
        _seed_activities(report_date=day, count=2)

    clear_cache()
    for day_offset in range(5):
        day = f"2026-07-{10 + day_offset:02d}"
        with page_read_scope():
            get_day_projection(day)

    assert cache_size() <= 3, f"cache has {cache_size()} slots, expected <= 3"


def test_source_version_mismatch_invalidates_cache(temp_db):
    """Structural change bumps generation → cache entry evicted."""
    activity_id = activity_factory.create_open_activity(
        start_time=f"{DATE} 09:00:00",
        app_name="App",
    )
    with page_read_scope():
        proj1 = get_day_projection(DATE)
    assert cache_size() == 1

    # Structural change via UoW bumps REPORT_STRUCTURE generation.
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        uow.connection.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )
        uow.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)

    with page_read_scope():
        proj2 = get_day_projection(DATE)
    assert proj2.source_version != proj1.source_version
    assert proj2.snapshot_revision != proj1.snapshot_revision


def test_non_structural_change_keeps_cache(temp_db):
    """Non-structural UPDATE (no UoW) does not invalidate the cache."""
    activity_id = activity_factory.create_closed_activity(
        day=DATE, start="09:00:00", end="09:30:00"
    )
    with page_read_scope():
        proj1 = get_day_projection(DATE)

    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = ?, updated_at = ? WHERE id = ?",
            (999, now_str(), activity_id),
        )

    with page_read_scope():
        proj2 = get_day_projection(DATE)
    assert proj2 is proj1, "non-structural change should not invalidate cache"


def test_transaction_bypass_does_not_read_or_write_cache(temp_db):
    """Mutation path (conn=) must not use the cross-request cache."""
    activity_factory.create_closed_activity(
        day=DATE, start="09:00:00", end="09:30:00"
    )
    # Populate the cache via page-read path.
    with page_read_scope():
        page_proj = get_day_projection(DATE)
    assert cache_size() == 1

    # Mutation path uses build_visible_snapshot with conn= directly.
    with get_connection() as conn:
        conn.execute("BEGIN")
        try:
            mutation_snapshot = build_visible_snapshot(DATE, DATE, conn=conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # The mutation snapshot is a ReportProjectionSnapshot, not a DayProjection.
    assert mutation_snapshot is not page_proj
    assert mutation_snapshot.snapshot_revision == page_proj.snapshot_revision


def test_transaction_rollback_does_not_pollute_cache(temp_db):
    """A rolled-back transaction must not corrupt the cross-request cache."""
    activity_factory.create_closed_activity(
        day=DATE, start="09:00:00", end="09:30:00"
    )
    with page_read_scope():
        original_proj = get_day_projection(DATE)

    # Start a transaction, make a change, then roll back.
    with get_connection() as conn:
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE activity_log SET status = ? WHERE status = ?",
            ("idle", "normal"),
        )
        # Build inside the transaction — should NOT affect the cache.
        build_visible_snapshot(DATE, DATE, conn=conn)
        conn.rollback()

    # After rollback, the cache should return the original projection.
    with page_read_scope():
        post_rollback_proj = get_day_projection(DATE)
    assert post_rollback_proj is original_proj, (
        "rollback leaked transaction-local state into the cache"
    )


def test_day_projection_indexes_reference_same_objects(temp_db):
    """entry_by_key and contributions_by_key must reference the same immutable objects."""
    _seed_activities(count=3)
    with page_read_scope():
        projection = get_day_projection(DATE)

    for entry in projection.entries:
        key = str(entry.get("projection_instance_key") or "")
        if key:
            assert projection.entry_by_key[key] is entry, (
                "entry_by_key must reference the same object, not a copy"
            )

    for contribution in projection.contributions:
        key = str(contribution.get("projection_instance_key") or "")
        if key:
            assert contribution in projection.contributions_by_key.get(key, ()), (
                "contributions_by_key must reference the same objects"
            )


def test_day_projection_does_not_store_duplicate_collections(temp_db):
    """DayProjection must not store final_sessions/standalone separately."""
    _seed_activities(count=3)
    with page_read_scope():
        projection = get_day_projection(DATE)

    # DayProjection should only have entries + contributions, not
    # separate final_sessions / standalone_status_entries storage.
    assert not hasattr(projection, "base_sessions"), (
        "DayProjection must not store mutation-only base_sessions"
    )
    # final_sessions is a derived property, not stored data.
    field_names = {f.name for f in projection.__dataclass_fields__.values()}
    assert "final_sessions" not in field_names, (
        "final_sessions must be a property, not a stored field"
    )
    assert "standalone_status_entries" not in field_names, (
        "standalone_status_entries must be a property, not a stored field"
    )


def test_clear_cache_forces_rebuild(temp_db):
    """clear_cache() must force the next read to rebuild from SQLite."""
    _seed_activities()
    with page_read_scope():
        proj1 = get_day_projection(DATE)

    clear_cache()
    assert cache_size() == 0

    build_calls = []
    original = report_projection_snapshot_service._build_snapshot

    def tracking_build(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    with patch(
        "worktrace.services.report_projection_provider._build_snapshot",
        side_effect=tracking_build,
    ):
        with page_read_scope():
            proj2 = get_day_projection(DATE)

    assert len(build_calls) == 1, "clear_cache should force a rebuild"
    assert proj2 is not proj1
    assert proj2.snapshot_revision == proj1.snapshot_revision


# --- expected_source_version stale guard ---


def test_detail_with_matching_source_version_succeeds(temp_db):
    """Detail call with the current source version must succeed."""
    _seed_activities(count=5)
    with page_read_scope():
        projection = get_day_projection(DATE)
    session = projection.final_sessions[0]
    key = str(session.get("projection_instance_key") or "")
    revision = str(session.get("projection_revision") or "")
    source_version = projection.source_version_token

    with page_read_scope():
        result = view_model_service.get_session_activity_summary_view_model(
            report_date=DATE,
            projection_instance_key=key,
            expected_projection_revision=revision,
            expected_source_version=source_version,
        )
    assert result["ok"] is True
    assert result["resolved_projection_revision"] == revision


def test_detail_with_stale_source_version_raises_stale_selection(temp_db):
    """Detail call with an outdated source version must raise stale_selection."""
    _seed_activities(count=5)
    with page_read_scope():
        projection = get_day_projection(DATE)
    session = projection.final_sessions[0]
    key = str(session.get("projection_instance_key") or "")
    revision = str(session.get("projection_revision") or "")

    with pytest.raises(ValueError, match="stale_selection"):
        with page_read_scope():
            view_model_service.get_session_activity_summary_view_model(
                report_date=DATE,
                projection_instance_key=key,
                expected_projection_revision=revision,
                expected_source_version="0" * 40,
            )


def test_detail_without_source_version_still_works(temp_db):
    """Omitting expected_source_version (backward compat) must succeed."""
    _seed_activities(count=5)
    with page_read_scope():
        projection = get_day_projection(DATE)
    session = projection.final_sessions[0]
    key = str(session.get("projection_instance_key") or "")
    revision = str(session.get("projection_revision") or "")

    with page_read_scope():
        result = view_model_service.get_session_activity_summary_view_model(
            report_date=DATE,
            projection_instance_key=key,
            expected_projection_revision=revision,
        )
    assert result["ok"] is True


def test_consecutive_detail_clicks_with_source_version_do_not_rebuild(temp_db):
    """20 detail clicks passing expected_source_version must not rebuild."""
    _seed_activities(count=10)
    clear_cache()

    with page_read_scope():
        projection = get_day_projection(DATE)
        assert len(projection.entries) >= 1

    sessions = projection.final_sessions
    assert len(sessions) >= 1
    key = str(sessions[0].get("projection_instance_key") or "")
    revision = str(sessions[0].get("projection_revision") or "")
    source_version = projection.source_version_token

    build_calls = []
    original = report_projection_snapshot_service._build_snapshot

    def tracking_build(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    with patch(
        "worktrace.services.report_projection_provider._build_snapshot",
        side_effect=tracking_build,
    ):
        for _ in range(20):
            with page_read_scope():
                view_model_service.get_session_activity_summary_view_model(
                    report_date=DATE,
                    projection_instance_key=key,
                    expected_projection_revision=revision,
                    expected_source_version=source_version,
                )

    assert len(build_calls) == 0, (
        f"detail clicks triggered {len(build_calls)} projection rebuilds"
    )
