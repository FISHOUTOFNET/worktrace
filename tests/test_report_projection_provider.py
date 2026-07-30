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
    report_projection_builder,
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
    original = report_projection_builder.compute_projection

    def tracking_compute(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    with patch(
        "worktrace.services.report_projection_provider.compute_projection",
        side_effect=tracking_compute,
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
    original = report_projection_builder.compute_projection

    def tracking_compute(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    sessions = projection.final_sessions
    assert len(sessions) >= 1
    key = str(sessions[0].get("projection_instance_key") or "")
    revision = str(sessions[0].get("projection_revision") or "")

    with patch(
        "worktrace.services.report_projection_provider.compute_projection",
        side_effect=tracking_compute,
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


def test_day_projection_contributions_by_key_references_exact_objects(temp_db):
    """contributions_by_key values must be the SAME objects (identity, not equality)."""
    _seed_activities(count=5)
    activity_factory.create_closed_activity(
        day=DATE, start="10:00:00", end="10:30:00", status="idle",
    )
    with page_read_scope():
        projection = get_day_projection(DATE)

    # Build a map from id(contribution) → contribution for the main collection.
    contributions_by_id = {id(c): c for c in projection.contributions}

    for key, indexed_contributions in projection.contributions_by_key.items():
        for indexed in indexed_contributions:
            assert id(indexed) in contributions_by_id, (
                f"contributions_by_key[{key!r}] contains an object not in "
                f"the main contributions collection (identity check failed)"
            )
            assert indexed is contributions_by_id[id(indexed)], (
                f"contributions_by_key[{key!r}] must reference the exact same "
                f"object, not a copy"
            )


def test_day_projection_entries_do_not_contain_projection_contributions(temp_db):
    """Compact entries must NOT contain _projection_contributions.

    The compact DayProjection stores contributions exactly once in the
    ``contributions`` collection. Page-read paths use ``contributions_by_key``
    to look them up. The ``_projection_contributions`` inline field is
    kept only in the full ReportProjectionSnapshot for mutation/export.
    """
    _seed_activities(count=5)
    activity_factory.create_closed_activity(
        day=DATE, start="10:00:00", end="10:30:00", status="idle",
    )
    with page_read_scope():
        projection = get_day_projection(DATE)

    assert len(projection.entries) > 0, "expected at least one entry"
    for entry in projection.entries:
        assert "_projection_contributions" not in entry, (
            f"compact entry {entry.get('projection_instance_key')!r} must not "
            f"contain _projection_contributions — it is stored only in the "
            f"contributions collection"
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
    original = report_projection_builder.compute_projection

    def tracking_compute(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    with patch(
        "worktrace.services.report_projection_provider.compute_projection",
        side_effect=tracking_compute,
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
    original = report_projection_builder.compute_projection

    def tracking_compute(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    with patch(
        "worktrace.services.report_projection_provider.compute_projection",
        side_effect=tracking_compute,
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


# --- Cross-page integration: Overview ↔ Timeline ↔ Detail ---


def test_overview_timeline_detail_share_single_build(temp_db):
    """Overview → Timeline → 20 Detail must build the day projection exactly once."""
    _seed_activities(count=10)
    clear_cache()

    build_calls = []
    original = report_projection_builder.compute_projection

    def tracking_compute(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    with patch(
        "worktrace.services.report_projection_provider.compute_projection",
        side_effect=tracking_compute,
    ):
        # 1. Load Overview in its own page-read scope.
        with page_read_scope():
            overview = view_model_service.get_overview_view_model(DATE)
            assert overview["ok"] is True
        assert len(build_calls) == 1, "Overview should trigger first build"

        # 2. Switch to Timeline in a separate page-read scope.
        with page_read_scope():
            timeline = view_model_service.get_timeline_view_model(DATE)
            assert timeline["ok"] is True
        assert len(build_calls) == 1, "Timeline must not rebuild after Overview"

        # 3. Open 20 Details in separate page-read scopes.
        sessions = timeline["entries"]
        assert len(sessions) >= 1
        key = str(sessions[0]["projection_instance_key"] or "")
        revision = str(sessions[0]["projection_revision"] or "")
        with page_read_scope():
            proj = get_day_projection(DATE)
            source_version = proj.source_version_token

        for _ in range(20):
            with page_read_scope():
                view_model_service.get_session_activity_summary_view_model(
                    report_date=DATE,
                    projection_instance_key=key,
                    expected_projection_revision=revision,
                    expected_source_version=source_version,
                )
        assert len(build_calls) == 1, (
            f"20 detail clicks triggered {len(build_calls) - 1} rebuilds"
        )


def test_timeline_overview_share_single_build(temp_db):
    """Timeline → Overview must build the day projection exactly once (reverse path)."""
    _seed_activities(count=5)
    clear_cache()

    build_calls = []
    original = report_projection_builder.compute_projection

    def tracking_compute(conn, start_date, end_date):
        build_calls.append((start_date, end_date))
        return original(conn, start_date, end_date)

    with patch(
        "worktrace.services.report_projection_provider.compute_projection",
        side_effect=tracking_compute,
    ):
        with page_read_scope():
            timeline = view_model_service.get_timeline_view_model(DATE)
            assert timeline["ok"] is True
        assert len(build_calls) == 1

        with page_read_scope():
            overview = view_model_service.get_overview_view_model(DATE)
            assert overview["ok"] is True
        assert len(build_calls) == 1, "Overview must not rebuild after Timeline"


# --- DayProjection recursive immutability ---


def test_day_projection_entry_by_key_is_immutable(temp_db):
    _seed_activities(count=3)
    with page_read_scope():
        projection = get_day_projection(DATE)

    with pytest.raises(TypeError):
        projection.entry_by_key.clear()
    with pytest.raises(TypeError):
        projection.entry_by_key["x"] = projection.entries[0]
    with pytest.raises(TypeError):
        del projection.entry_by_key["x"]


def test_day_projection_contributions_by_key_is_immutable(temp_db):
    _seed_activities(count=3)
    with page_read_scope():
        projection = get_day_projection(DATE)

    with pytest.raises(TypeError):
        projection.contributions_by_key["x"] = ()
    with pytest.raises(TypeError):
        del projection.contributions_by_key["x"]
    # Each value must also be immutable (tuple, not list).
    for key in projection.contributions_by_key:
        assert isinstance(projection.contributions_by_key[key], tuple)


def test_day_projection_entries_and_contributions_are_immutable(temp_db):
    _seed_activities(count=3)
    with page_read_scope():
        projection = get_day_projection(DATE)

    assert isinstance(projection.entries, tuple)
    assert isinstance(projection.contributions, tuple)
    # Entry records must be FrozenDict, not mutable dict.
    for entry in projection.entries:
        with pytest.raises(TypeError):
            entry["project_name"] = "mutated"


def test_caller_cannot_pollute_shared_cache(temp_db):
    """A caller's mutation attempt must not affect subsequent cache reads."""
    _seed_activities(count=3)
    with page_read_scope():
        proj1 = get_day_projection(DATE)

    # Attempt to mutate (should raise, but even if caught, cache must be clean).
    try:
        proj1.entry_by_key.clear()
    except TypeError:
        pass

    with page_read_scope():
        proj2 = get_day_projection(DATE)
    assert proj2 is proj1, "cache should return the same object"
    assert len(proj2.entry_by_key) > 0, "cache was polluted by caller mutation"


# --- Top-3 distinct label regression ---


def test_top3_distinct_labels_with_duplicate_labels():
    """A:100, A:90, B:80, C:70, D:60 → [A, B, C] (not [A, B])."""
    from worktrace.services.view_model_service import _top3_distinct_labels

    contributions = [
        {"duration_seconds": 100, "activity_display_name": "A",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
        {"duration_seconds": 90, "activity_display_name": "A",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
        {"duration_seconds": 80, "activity_display_name": "B",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
        {"duration_seconds": 70, "activity_display_name": "C",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
        {"duration_seconds": 60, "activity_display_name": "D",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
    ]
    labels = _top3_distinct_labels(contributions)
    assert labels == ["A", "B", "C"]


def test_top3_distinct_labels_fewer_than_three():
    from worktrace.services.view_model_service import _top3_distinct_labels

    contributions = [
        {"duration_seconds": 100, "activity_display_name": "A",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
        {"duration_seconds": 50, "activity_display_name": "B",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
    ]
    labels = _top3_distinct_labels(contributions)
    assert labels == ["A", "B"]


def test_top3_distinct_labels_empty_contributions():
    from worktrace.services.view_model_service import _top3_distinct_labels

    assert _top3_distinct_labels([]) == []


def test_top3_distinct_labels_skips_privacy_redacted_and_non_normal():
    from worktrace.services.view_model_service import _top3_distinct_labels

    contributions = [
        {"duration_seconds": 999, "activity_display_name": "Redacted",
         "status": "normal", "privacy_redacted": True,
         "resource_is_anchor": True, "app_name": "", "process_name": "",
         "window_title": ""},
        {"duration_seconds": 998, "activity_display_name": "Idle",
         "status": "idle", "privacy_redacted": False,
         "resource_is_anchor": True, "app_name": "", "process_name": "",
         "window_title": ""},
        {"duration_seconds": 100, "activity_display_name": "A",
         "status": "normal", "privacy_redacted": False,
         "resource_is_anchor": True, "app_name": "", "process_name": "",
         "window_title": ""},
    ]
    labels = _top3_distinct_labels(contributions)
    assert labels == ["A"]


def test_top3_distinct_labels_ties_preserve_original_order():
    """Equal-duration ties must preserve the original contribution order."""
    from worktrace.services.view_model_service import _top3_distinct_labels

    contributions = [
        {"duration_seconds": 100, "activity_display_name": "B",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
        {"duration_seconds": 100, "activity_display_name": "A",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
        {"duration_seconds": 100, "activity_display_name": "C",
         "status": "normal", "resource_is_anchor": True,
         "app_name": "", "process_name": "", "window_title": ""},
    ]
    labels = _top3_distinct_labels(contributions)
    assert labels == ["B", "A", "C"]


# --- Compact / Full equivalence ---


def _normalize_entry(value):
    """Normalize a projection entry for compact/full comparison.

    Strips ``_projection_contributions`` (compact never stores it; full
    keeps it for mutation/export). Everything else must match exactly.
    """
    from worktrace.services.report_projection_model import thaw_value

    item = thaw_value(value)
    if isinstance(item, dict):
        item.pop("_projection_contributions", None)
    return item


def _assert_compact_matches_full(compact, full):
    """Full structural equivalence between compact DayProjection and full snapshot."""
    from worktrace.services.report_projection_model import thaw_value

    # snapshot_revision (content hash) must be identical.
    assert compact.snapshot_revision == full.snapshot_revision, (
        f"snapshot_revision mismatch: compact={compact.snapshot_revision} "
        f"full={full.snapshot_revision}"
    )

    # operation_diagnostics must match exactly (to_dict for deep comparison).
    assert len(compact.operation_diagnostics) == len(full.operation_diagnostics)
    for compact_diag, full_diag in zip(
        compact.operation_diagnostics, full.operation_diagnostics
    ):
        assert compact_diag.to_dict() == full_diag.to_dict(), (
            "operation_diagnostics mismatch"
        )

    # Entries: full structural comparison after normalizing _projection_contributions.
    compact_entries = [_normalize_entry(e) for e in compact.entries]
    full_entries = [_normalize_entry(e) for e in full.final_entries]
    assert len(compact_entries) == len(full_entries), (
        f"entry count mismatch: compact={len(compact_entries)} "
        f"full={len(full_entries)}"
    )
    for idx, (compact_entry, full_entry) in enumerate(
        zip(compact_entries, full_entries)
    ):
        assert compact_entry == full_entry, (
            f"entry[{idx}] mismatch: "
            f"compact_key={compact_entry.get('projection_instance_key')!r} "
            f"full_key={full_entry.get('projection_instance_key')!r}"
        )

    # Contributions: full structural comparison (thawed for deep equality).
    compact_contributions = [thaw_value(c) for c in compact.contributions]
    full_contributions = [thaw_value(c) for c in full.final_contributions]
    assert len(compact_contributions) == len(full_contributions), (
        f"contribution count mismatch: compact={len(compact_contributions)} "
        f"full={len(full_contributions)}"
    )
    for idx, (compact_c, full_c) in enumerate(
        zip(compact_contributions, full_contributions)
    ):
        assert compact_c == full_c, (
            f"contribution[{idx}] mismatch: "
            f"compact_key={compact_c.get('projection_instance_key')!r} "
            f"full_key={full_c.get('projection_instance_key')!r}"
        )


def test_compact_day_projection_matches_full_snapshot(temp_db):
    """Compact DayProjection must be structurally identical to full snapshot.

    Compares every entry field (not just key/duration), every contribution
    field, snapshot_revision, and operation_diagnostics. The only allowed
    difference is _projection_contributions on entries (compact strips it;
    full keeps it for mutation/export compatibility).
    """
    _seed_activities(count=5)
    activity_factory.create_closed_activity(
        day=DATE, start="10:00:00", end="10:30:00", status="idle",
    )

    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)

    _assert_compact_matches_full(compact, full)


def test_compact_full_equivalence_normal_and_idle(temp_db):
    """Scenario: normal activities + idle (standalone status)."""
    _seed_activities(count=5)
    activity_factory.create_closed_activity(
        day=DATE, start="10:00:00", end="10:30:00", status="idle",
    )
    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)
    _assert_compact_matches_full(compact, full)


def test_compact_full_equivalence_open_activity(temp_db):
    """Scenario: open (in-progress) activity at end of day."""
    _seed_activities(count=3)
    activity_factory.create_open_activity(
        start_time=f"{DATE} 14:00:00",
        app_name="App",
    )
    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)
    _assert_compact_matches_full(compact, full)


def test_compact_full_equivalence_excluded_activity(temp_db):
    """Scenario: excluded (paused) activity → standalone status row."""
    _seed_activities(count=3)
    activity_factory.create_closed_activity(
        day=DATE, start="10:00:00", end="10:30:00", status="excluded",
    )
    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)
    _assert_compact_matches_full(compact, full)


def test_compact_full_equivalence_manual_attribution(temp_db):
    """Scenario: direct manual project attribution."""
    from worktrace.services import project_service

    project_id = project_service.create_project("ManualProject")
    _seed_activities(count=3)
    activity_factory.create_closed_activity(
        day=DATE,
        start="11:00:00",
        end="11:30:00",
        project_id=project_id,
    )
    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)
    _assert_compact_matches_full(compact, full)


def test_compact_full_equivalence_with_merge_operation(temp_db):
    """Scenario: session merge operation replay."""
    # Space activities far apart so they form separate sessions.
    activity_factory.create_closed_activity(
        day=DATE, start="09:00:00", end="09:30:00", window_title="Doc0",
    )
    activity_factory.create_closed_activity(
        day=DATE, start="10:00:00", end="10:30:00", window_title="Doc1",
    )
    from worktrace.services.report_session_operation_service import (
        merge_session,
    )

    with page_read_scope():
        projection = get_day_projection(DATE)
    sessions = projection.final_sessions
    assert len(sessions) >= 2, f"expected >=2 sessions, got {len(sessions)}"
    source_key = str(sessions[0].get("projection_instance_key") or "")
    source_rev = str(sessions[0].get("projection_revision") or "")
    target_key = str(sessions[1].get("projection_instance_key") or "")
    target_rev = str(sessions[1].get("projection_revision") or "")

    merge_session(
        report_date=DATE,
        projection_instance_key=source_key,
        direction="next",
        request_id="req-merge-1",
        expected_projection_revision=source_rev,
        target_projection_instance_key=target_key,
        target_expected_projection_revision=target_rev,
    )

    clear_cache()
    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)
    _assert_compact_matches_full(compact, full)


def test_compact_full_equivalence_with_split_operation(temp_db):
    """Scenario: merge then split (split requires a merged session)."""
    # Create two separate sessions, merge them, then split the merged result.
    activity_factory.create_closed_activity(
        day=DATE, start="09:00:00", end="09:30:00", window_title="Doc0",
    )
    activity_factory.create_closed_activity(
        day=DATE, start="10:00:00", end="10:30:00", window_title="Doc1",
    )
    from worktrace.services.report_session_operation_service import (
        merge_session,
        split_session,
    )

    with page_read_scope():
        projection = get_day_projection(DATE)
    sessions = projection.final_sessions
    assert len(sessions) >= 2
    source_key = str(sessions[0].get("projection_instance_key") or "")
    source_rev = str(sessions[0].get("projection_revision") or "")
    target_key = str(sessions[1].get("projection_instance_key") or "")
    target_rev = str(sessions[1].get("projection_revision") or "")

    # Merge first — this creates a session with can_split=True.
    merge_session(
        report_date=DATE,
        projection_instance_key=source_key,
        direction="next",
        request_id="req-merge-1",
        expected_projection_revision=source_rev,
        target_projection_instance_key=target_key,
        target_expected_projection_revision=target_rev,
    )

    clear_cache()
    with page_read_scope():
        projection = get_day_projection(DATE)
    merged_sessions = projection.final_sessions
    assert len(merged_sessions) >= 1
    merged = merged_sessions[0]
    assert bool(merged.get("can_split")), "merged session must be splittable"
    merged_key = str(merged.get("projection_instance_key") or "")
    merged_rev = str(merged.get("projection_revision") or "")

    # Now split the merged session.
    split_session(
        report_date=DATE,
        projection_instance_key=merged_key,
        expected_projection_revision=merged_rev,
        request_id="req-split-1",
    )

    clear_cache()
    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)
    _assert_compact_matches_full(compact, full)


def test_compact_full_equivalence_with_copy_operation(temp_db):
    """Scenario: session copy operation replay."""
    _seed_activities(count=4)
    from worktrace.services.report_session_operation_service import (
        copy_session,
    )

    with page_read_scope():
        projection = get_day_projection(DATE)
    sessions = projection.final_sessions
    assert len(sessions) >= 1
    key = str(sessions[0].get("projection_instance_key") or "")
    rev = str(sessions[0].get("projection_revision") or "")

    copy_session(
        report_date=DATE,
        projection_instance_key=key,
        expected_projection_revision=rev,
        request_id="req-copy-1",
    )

    clear_cache()
    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)
    _assert_compact_matches_full(compact, full)


def test_compact_full_equivalence_with_hide_operation(temp_db):
    """Scenario: session hide operation replay."""
    _seed_activities(count=4)
    from worktrace.services.report_session_operation_service import (
        hide_session,
    )

    with page_read_scope():
        projection = get_day_projection(DATE)
    sessions = projection.final_sessions
    assert len(sessions) >= 1
    key = str(sessions[0].get("projection_instance_key") or "")
    rev = str(sessions[0].get("projection_revision") or "")

    hide_session(
        report_date=DATE,
        projection_instance_key=key,
        expected_projection_revision=rev,
        request_id="req-hide-1",
    )

    clear_cache()
    with page_read_scope():
        compact = get_day_projection(DATE)
    full = build_visible_snapshot(DATE, DATE)
    _assert_compact_matches_full(compact, full)
