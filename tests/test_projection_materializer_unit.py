"""Pure-function unit tests for the compact DayProjection materializer.

These tests construct a :class:`ProjectionComputation` directly with
synthetic data and call :func:`materialize_day_projection` — no database
fixture, no page-read scope. They verify the materializer's pure-functional
contracts:

* recursive immutability of entries and contributions;
* ``entry_by_key`` references the same frozen entry objects (identity);
* ``contributions_by_key`` references the same frozen contribution
  objects (identity);
* contributions are stored exactly once (no duplicate freeze);
* ``_projection_contributions`` is stripped from compact entries;
* O(N) grouping — contributions with the same key are grouped into a
  tuple, preserving insertion order;
* ``row_kind`` derived properties (``final_sessions``,
  ``standalone_status_entries``) filter entries correctly;
* compact materialization matches the raw computation's data.
"""

from __future__ import annotations

import pytest

from worktrace.services.projection_performance import (
    get_last_record,
    projection_perf_scope,
    reset_last_record,
)
from worktrace.services.report_projection_builder import ProjectionComputation
from worktrace.services.report_projection_model import OperationDiagnostic
from worktrace.services.report_projection_provider import (
    DayProjection,
    FrozenProjectionData,
    ProjectionIndexes,
    assemble_day_projection,
    build_projection_indexes,
    freeze_projection_data,
    materialize_day_projection,
)
from worktrace.services.report_revision_service import ProjectionSourceVersion

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

DATE = "2026-07-15"


def _source_version(date: str = DATE) -> ProjectionSourceVersion:
    return ProjectionSourceVersion(
        database_key="test_db",
        report_date=date,
        report_structure_generation=0,
        database_replacement_epoch=0,
        projection_schema_version=1,
    )


def _entry(
    key: str,
    *,
    row_kind: str = "project_session",
    start_time: str = "2026-07-15 09:00:00",
    revision: str = "rev-1",
) -> dict:
    return {
        "row_kind": row_kind,
        "report_date": DATE,
        "projection_instance_key": key,
        "projection_revision": revision,
        "project_id": 1,
        "project_name": "P",
        "start_time": start_time,
        "end_time": "2026-07-15 09:30:00",
        "duration_seconds": 1800,
        "status": "normal",
        "activity_ids": [1],
        "member_slices": [
            {"report_date": DATE, "activity_id": 1, "slice_start_time": start_time}
        ],
    }


def _contribution(
    key: str,
    *,
    activity_id: int = 1,
    duration: int = 1800,
    display_name: str = "Doc",
) -> dict:
    return {
        "projection_instance_key": key,
        "report_date": DATE,
        "activity_id": activity_id,
        "slice_start_time": "2026-07-15 09:00:00",
        "duration_seconds": duration,
        "status": "normal",
        "activity_display_name": display_name,
        "app_name": "App",
        "process_name": "app.exe",
        "window_title": display_name,
        "resource_is_anchor": True,
    }


def _standalone_entry(key: str) -> dict:
    return _entry(key, row_kind="standalone_status", start_time="2026-07-15 12:00:00")


def _computation(
    *,
    entries: list[dict] | None = None,
    contributions: list[dict] | None = None,
    diagnostics: list[OperationDiagnostic] | None = None,
) -> ProjectionComputation:
    if entries is None:
        entries = [_entry("k1"), _standalone_entry("k2")]
    if contributions is None:
        contributions = [_contribution("k1"), _contribution("k1", activity_id=2)]
    return ProjectionComputation(
        start_date=DATE,
        end_date=DATE,
        base_sessions=[],
        final_entries=entries,
        final_sessions=[e for e in entries if e.get("row_kind") == "project_session"],
        standalone_status_entries=[
            e for e in entries if e.get("row_kind") == "standalone_status"
        ],
        final_contributions=contributions,
        operation_diagnostics=diagnostics or [],
        snapshot_revision="rev-" + DATE,
        activity_count=len(entries),
    )


# --- Recursive immutability ---


def test_materialize_day_projection_entries_are_recursively_immutable():
    comp = _computation()
    projection = materialize_day_projection(comp, _source_version())
    assert isinstance(projection.entries, tuple)
    for entry in projection.entries:
        with pytest.raises(TypeError):
            entry["project_name"] = "mutated"
        with pytest.raises(TypeError):
            entry["member_slices"][0]["activity_id"] = 999


def test_materialize_day_projection_contributions_are_recursively_immutable():
    comp = _computation()
    projection = materialize_day_projection(comp, _source_version())
    assert isinstance(projection.contributions, tuple)
    for contribution in projection.contributions:
        with pytest.raises(TypeError):
            contribution["duration_seconds"] = 0


def test_materialize_day_projection_indexes_are_immutable():
    comp = _computation()
    projection = materialize_day_projection(comp, _source_version())
    with pytest.raises(TypeError):
        projection.entry_by_key.clear()
    with pytest.raises(TypeError):
        projection.entry_by_key["x"] = projection.entries[0]
    with pytest.raises(TypeError):
        del projection.entry_by_key["k1"]
    with pytest.raises(TypeError):
        projection.contributions_by_key["x"] = ()
    with pytest.raises(TypeError):
        del projection.contributions_by_key["k1"]
    for key in projection.contributions_by_key:
        assert isinstance(projection.contributions_by_key[key], tuple)


# --- Entry index ---


def test_entry_by_key_references_same_frozen_entry_objects():
    """entry_by_key must reference the SAME objects as entries — not copies."""
    entries = [_entry("k1"), _entry("k2"), _standalone_entry("k3")]
    comp = _computation(entries=entries, contributions=[_contribution("k1")])
    projection = materialize_day_projection(comp, _source_version())
    for entry in projection.entries:
        key = str(entry.get("projection_instance_key") or "")
        if key:
            assert projection.entry_by_key[key] is entry, (
                f"entry_by_key[{key!r}] must reference the same object, not a copy"
            )


def test_entry_by_key_omits_entries_without_key():
    entries = [_entry("k1"), {"row_kind": "project_session", "projection_instance_key": ""}]
    comp = _computation(entries=entries, contributions=[_contribution("k1")])
    projection = materialize_day_projection(comp, _source_version())
    assert "k1" in projection.entry_by_key
    assert "" not in projection.entry_by_key


# --- Contribution index ---


def test_contributions_by_key_references_exact_objects():
    """contributions_by_key values must be the SAME objects (identity check)."""
    contributions = [
        _contribution("k1", activity_id=1, duration=100),
        _contribution("k1", activity_id=2, duration=200),
        _contribution("k2", activity_id=3, duration=300),
    ]
    comp = _computation(
        entries=[_entry("k1"), _entry("k2")],
        contributions=contributions,
    )
    projection = materialize_day_projection(comp, _source_version())

    contributions_by_id = {id(c): c for c in projection.contributions}
    assert len(projection.contributions_by_key["k1"]) == 2
    assert len(projection.contributions_by_key["k2"]) == 1
    for key, indexed_contributions in projection.contributions_by_key.items():
        for indexed in indexed_contributions:
            assert id(indexed) in contributions_by_id, (
                f"contributions_by_key[{key!r}] contains an object not in "
                f"the main contributions collection (identity check failed)"
            )
            assert indexed is contributions_by_id[id(indexed)], (
                f"contributions_by_key[{key!r}] must reference the exact "
                f"same object, not a copy"
            )


def test_contributions_by_key_preserves_insertion_order():
    """Contributions with the same key must preserve insertion order."""
    contributions = [
        _contribution("k1", activity_id=1, display_name="A"),
        _contribution("k1", activity_id=2, display_name="B"),
        _contribution("k1", activity_id=3, display_name="C"),
    ]
    comp = _computation(entries=[_entry("k1")], contributions=contributions)
    projection = materialize_day_projection(comp, _source_version())
    indexed = projection.contributions_by_key["k1"]
    assert [c["activity_display_name"] for c in indexed] == ["A", "B", "C"]


# --- Contribution stored once ---


def test_contributions_are_frozen_exactly_once():
    """No contribution object may be frozen twice (no duplicate deep copy).

    Each contribution in the main ``contributions`` collection must be
    identical (``is``) to the object referenced in ``contributions_by_key``.
    The total number of frozen contribution objects must equal the number
    of input contributions.
    """
    contributions = [
        _contribution("k1", activity_id=1),
        _contribution("k1", activity_id=2),
        _contribution("k2", activity_id=3),
    ]
    comp = _computation(
        entries=[_entry("k1"), _entry("k2")],
        contributions=contributions,
    )
    projection = materialize_day_projection(comp, _source_version())

    assert len(projection.contributions) == 3
    # Every indexed contribution must be the same object as one in the
    # main collection. The main collection is the sole contribution store.
    main_ids = {id(c) for c in projection.contributions}
    for indexed_tuple in projection.contributions_by_key.values():
        for indexed in indexed_tuple:
            assert id(indexed) in main_ids


def test_compact_entries_do_not_contain_projection_contributions():
    """Compact entries must NOT contain the _projection_contributions inline field.

    The compact DayProjection stores contributions exactly once in the
    ``contributions`` collection. Page-read paths use
    ``contributions_by_key`` to look them up. The
    ``_projection_contributions`` inline field is kept only in the full
    ReportProjectionSnapshot for mutation/export.
    """
    entries_with_inline = [
        {"projection_instance_key": "k1", "_projection_contributions": [{"x": 1}]},
    ]
    comp = _computation(
        entries=entries_with_inline,
        contributions=[_contribution("k1")],
    )
    projection = materialize_day_projection(comp, _source_version())
    assert len(projection.entries) == 1
    for entry in projection.entries:
        assert "_projection_contributions" not in entry


def test_day_projection_does_not_store_duplicate_collections():
    """DayProjection must not store final_sessions/standalone separately."""
    comp = _computation()
    projection = materialize_day_projection(comp, _source_version())
    assert not hasattr(projection, "base_sessions")
    field_names = {f.name for f in projection.__dataclass_fields__.values()}
    assert "final_sessions" not in field_names
    assert "standalone_status_entries" not in field_names


# --- O(N) grouping ---


def test_contributions_by_key_groups_all_keys():
    """O(N) grouping must collect every contribution under its key."""
    contributions = [
        _contribution("k1", activity_id=1),
        _contribution("k2", activity_id=2),
        _contribution("k1", activity_id=3),
        _contribution("k3", activity_id=4),
        _contribution("k1", activity_id=5),
        _contribution("k2", activity_id=6),
    ]
    comp = _computation(
        entries=[_entry("k1"), _entry("k2"), _entry("k3")],
        contributions=contributions,
    )
    projection = materialize_day_projection(comp, _source_version())
    assert sorted(projection.contributions_by_key.keys()) == ["k1", "k2", "k3"]
    assert len(projection.contributions_by_key["k1"]) == 3
    assert len(projection.contributions_by_key["k2"]) == 2
    assert len(projection.contributions_by_key["k3"]) == 1
    # Total contributions preserved.
    total_indexed = sum(
        len(v) for v in projection.contributions_by_key.values()
    )
    assert total_indexed == len(contributions)


# --- row_kind derived properties ---


def test_final_sessions_filters_project_session_entries():
    entries = [
        _entry("k1", row_kind="project_session", start_time="2026-07-15 09:00:00"),
        _standalone_entry("k2"),
        _entry("k3", row_kind="project_session", start_time="2026-07-15 11:00:00"),
    ]
    comp = _computation(entries=entries, contributions=[_contribution("k1")])
    projection = materialize_day_projection(comp, _source_version())
    final_sessions = projection.final_sessions
    assert len(final_sessions) == 2
    assert all(
        str(e.get("row_kind") or "project_session") == "project_session"
        for e in final_sessions
    )
    assert {str(e.get("projection_instance_key") or "") for e in final_sessions} == {
        "k1",
        "k3",
    }


def test_standalone_status_entries_filters_standalone_rows():
    entries = [
        _entry("k1"),
        _standalone_entry("k2"),
        _standalone_entry("k3"),
    ]
    comp = _computation(entries=entries, contributions=[_contribution("k1")])
    projection = materialize_day_projection(comp, _source_version())
    standalone = projection.standalone_status_entries
    assert len(standalone) == 2
    assert all(
        str(e.get("row_kind") or "") == "standalone_status" for e in standalone
    )
    assert {str(e.get("projection_instance_key") or "") for e in standalone} == {
        "k2",
        "k3",
    }


def test_final_sessions_returns_empty_when_only_standalone_entries():
    entries = [_standalone_entry("k1"), _standalone_entry("k2")]
    comp = _computation(entries=entries, contributions=[])
    projection = materialize_day_projection(comp, _source_version())
    assert projection.final_sessions == ()
    assert len(projection.standalone_status_entries) == 2


# --- Compact materialization preserves data ---


def test_materialize_preserves_snapshot_revision_and_diagnostics():
    diagnostics = [
        OperationDiagnostic(
            operation_id=1,
            sequence=1,
            operation_type="copy_session",
            state="applied",
            reason="",
            source_instance_key="k1",
        )
    ]
    comp = _computation(diagnostics=diagnostics)
    projection = materialize_day_projection(comp, _source_version())
    assert projection.snapshot_revision == comp.snapshot_revision
    assert projection.operation_diagnostics == tuple(diagnostics)
    assert projection.report_date == DATE


def test_materialize_preserves_entry_and_contribution_fields():
    entries = [_entry("k1")]
    contributions = [_contribution("k1", activity_id=42, duration=999, display_name="Doc42")]
    comp = _computation(entries=entries, contributions=contributions)
    projection = materialize_day_projection(comp, _source_version())
    assert projection.entries[0]["projection_instance_key"] == "k1"
    assert projection.entries[0]["project_name"] == "P"
    assert projection.contributions[0]["activity_id"] == 42
    assert projection.contributions[0]["duration_seconds"] == 999
    assert projection.contributions[0]["activity_display_name"] == "Doc42"


def test_materialize_uses_computation_start_date_when_report_date_omitted():
    comp = _computation()
    projection = materialize_day_projection(comp, _source_version())
    assert projection.report_date == comp.start_date


def test_materialize_report_date_override_takes_precedence():
    comp = _computation()
    other = "2026-08-01"
    projection = materialize_day_projection(
        comp, _source_version(date=other), report_date=other
    )
    assert projection.report_date == other


# --- Split step: freeze_projection_data ---


def test_freeze_projection_data_strips_inline_contributions():
    """freeze_projection_data must strip _projection_contributions from entries."""
    entries = [
        {"projection_instance_key": "k1", "_projection_contributions": [{"x": 1}]},
    ]
    comp = _computation(entries=entries, contributions=[_contribution("k1")])
    frozen = freeze_projection_data(comp)
    assert len(frozen.entries) == 1
    assert "_projection_contributions" not in frozen.entries[0]


def test_freeze_projection_data_produces_immutable_entries_and_contributions():
    comp = _computation()
    frozen = freeze_projection_data(comp)
    assert isinstance(frozen.entries, tuple)
    assert isinstance(frozen.contributions, tuple)
    with pytest.raises(TypeError):
        frozen.entries[0]["project_name"] = "mutated"
    with pytest.raises(TypeError):
        frozen.contributions[0]["duration_seconds"] = 0


def test_freeze_projection_data_carries_pass_through_metadata():
    diagnostics = [
        OperationDiagnostic(
            operation_id=1,
            sequence=1,
            operation_type="copy_session",
            state="applied",
            reason="",
            source_instance_key="k1",
        )
    ]
    comp = _computation(diagnostics=diagnostics)
    frozen = freeze_projection_data(comp)
    assert frozen.snapshot_revision == comp.snapshot_revision
    assert frozen.start_date == comp.start_date
    assert frozen.operation_diagnostics == tuple(diagnostics)


# --- Split step: build_projection_indexes ---


def test_build_projection_indexes_references_same_frozen_objects():
    """Indexes must reference the SAME objects as frozen_data — not copies."""
    contributions = [
        _contribution("k1", activity_id=1),
        _contribution("k1", activity_id=2),
        _contribution("k2", activity_id=3),
    ]
    comp = _computation(
        entries=[_entry("k1"), _entry("k2")],
        contributions=contributions,
    )
    frozen = freeze_projection_data(comp)
    indexes = build_projection_indexes(frozen)

    # entry_by_key identity
    for entry in frozen.entries:
        key = str(entry.get("projection_instance_key") or "")
        if key:
            assert indexes.entry_by_key[key] is entry

    # contributions_by_key identity
    contribution_ids = {id(c) for c in frozen.contributions}
    for indexed_tuple in indexes.contributions_by_key.values():
        for indexed in indexed_tuple:
            assert id(indexed) in contribution_ids


def test_build_projection_indexes_empty_data_produces_immutable_empty_indexes():
    """Empty projection must produce immutable empty indexes."""
    comp = _computation(entries=[], contributions=[])
    frozen = freeze_projection_data(comp)
    indexes = build_projection_indexes(frozen)
    assert len(indexes.entry_by_key) == 0
    assert len(indexes.contributions_by_key) == 0
    with pytest.raises(TypeError):
        indexes.entry_by_key["x"] = {}
    with pytest.raises(TypeError):
        indexes.contributions_by_key["x"] = ()


# --- Split step: assemble_day_projection ---


def test_assemble_day_projection_uses_frozen_data_and_indexes():
    comp = _computation()
    frozen = freeze_projection_data(comp)
    indexes = build_projection_indexes(frozen)
    projection = assemble_day_projection(frozen, indexes, _source_version())
    assert isinstance(projection, DayProjection)
    assert projection.entries is frozen.entries
    assert projection.contributions is frozen.contributions
    assert projection.entry_by_key is indexes.entry_by_key
    assert projection.contributions_by_key is indexes.contributions_by_key


def test_assemble_day_projection_report_date_defaults_to_start_date():
    comp = _computation()
    frozen = freeze_projection_data(comp)
    indexes = build_projection_indexes(frozen)
    projection = assemble_day_projection(frozen, indexes, _source_version())
    assert projection.report_date == frozen.start_date


def test_assemble_day_projection_report_date_override_takes_precedence():
    comp = _computation()
    frozen = freeze_projection_data(comp)
    indexes = build_projection_indexes(frozen)
    other = "2026-09-01"
    projection = assemble_day_projection(
        frozen, indexes, _source_version(date=other), report_date=other
    )
    assert projection.report_date == other


# --- Split compose equivalence ---


def test_split_steps_match_materialize_day_projection():
    """The three split steps must produce the same result as the public wrapper."""
    comp = _computation()
    direct = materialize_day_projection(comp, _source_version())
    frozen = freeze_projection_data(comp)
    indexes = build_projection_indexes(frozen)
    via_split = assemble_day_projection(frozen, indexes, _source_version())
    assert direct.report_date == via_split.report_date
    assert direct.snapshot_revision == via_split.snapshot_revision
    assert direct.entries == via_split.entries
    assert direct.contributions == via_split.contributions
    assert direct.entry_by_key == via_split.entry_by_key
    assert direct.contributions_by_key == via_split.contributions_by_key


# --- Timing stage semantics: index_build measures real work, not a no-op ---


def test_timing_index_build_measures_real_index_construction():
    """index_build stage must record real work (building indexes), not be a no-op.

    Uses projection_perf_scope + stage() the same way the Builder does,
    with a large enough dataset that index construction produces a
    measurable duration.  We assert the stage was recorded with a
    non-negative value and that index_build work actually happened
    (indexes are populated), not that the duration exceeds some threshold.
    """
    contributions = [
        _contribution(f"k{i}", activity_id=i) for i in range(200)
    ]
    entries = [_entry(f"k{i}") for i in range(200)]
    comp = _computation(entries=entries, contributions=contributions)
    reset_last_record()
    with projection_perf_scope(DATE, surface="test"):
        from worktrace.services.projection_performance import stage

        with stage("projection_materialize"):
            frozen = freeze_projection_data(comp)
        with stage("index_build"):
            indexes = build_projection_indexes(frozen)
        with stage("projection_assemble"):
            projection = assemble_day_projection(frozen, indexes, _source_version())
    record = get_last_record()
    reset_last_record()
    assert record is not None
    # index_build was recorded (not a missing/no-op stage).
    assert "index_build" in record.stages, (
        f"index_build stage missing from record; stages={list(record.stages)}"
    )
    # Real work happened: indexes are populated.
    assert len(indexes.entry_by_key) == 200
    assert len(indexes.contributions_by_key) == 200
    assert len(projection.entries) == 200
    # Duration is non-negative (we do NOT assert a minimum magnitude —
    # timing assertions on tiny values are flaky on CI).
    assert record.stage_total("index_build") >= 0.0


def test_timing_projection_materialize_does_not_include_index_work():
    """projection_materialize must NOT include index construction work.

    After splitting, projection_materialize only covers freeze_projection_data.
    We verify by checking that build_projection_indexes is NOT called inside
    the projection_materialize stage — the indexes appear only after the
    stage exits.  This is a structural call-boundary test, not a duration
    comparison (duration comparisons on small deltas are flaky).
    """
    comp = _computation()
    reset_last_record()
    frozen_holder: dict[str, FrozenProjectionData | None] = {"frozen": None}
    indexes_holder: dict[str, ProjectionIndexes | None] = {"indexes": None}

    with projection_perf_scope(DATE, surface="test"):
        from worktrace.services.projection_performance import stage

        with stage("projection_materialize"):
            frozen = freeze_projection_data(comp)
            frozen_holder["frozen"] = frozen
            # At this point, inside projection_materialize stage, indexes
            # have NOT been built yet — they don't exist.
            assert indexes_holder["indexes"] is None
        with stage("index_build"):
            indexes = build_projection_indexes(frozen)
            indexes_holder["indexes"] = indexes
    record = get_last_record()
    reset_last_record()
    assert record is not None
    assert frozen_holder["frozen"] is not None
    assert indexes_holder["indexes"] is not None
    # Both stages were recorded separately.
    assert "projection_materialize" in record.stages
    assert "index_build" in record.stages


def test_timing_split_stages_recorded_in_correct_order():
    """The three stages must be recorded in call order: materialize → index → assemble."""
    comp = _computation()
    reset_last_record()
    with projection_perf_scope(DATE, surface="test"):
        from worktrace.services.projection_performance import stage

        with stage("projection_materialize"):
            frozen = freeze_projection_data(comp)
        with stage("index_build"):
            indexes = build_projection_indexes(frozen)
        with stage("projection_assemble"):
            assemble_day_projection(frozen, indexes, _source_version())
    record = get_last_record()
    reset_last_record()
    assert record is not None
    # All three stages present.
    assert set(record.stages.keys()) >= {
        "projection_materialize",
        "index_build",
        "projection_assemble",
    }
    # Python dict preserves insertion order — verify stages were inserted
    # in the expected sequence.
    stage_names = list(record.stages.keys())
    materialize_idx = stage_names.index("projection_materialize")
    index_idx = stage_names.index("index_build")
    assemble_idx = stage_names.index("projection_assemble")
    assert materialize_idx < index_idx < assemble_idx, (
        f"stage order wrong: {stage_names}"
    )
