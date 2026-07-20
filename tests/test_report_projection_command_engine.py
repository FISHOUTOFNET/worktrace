from __future__ import annotations

from copy import deepcopy

import pytest

from worktrace.services import report_session_operation_engine as engine
from worktrace.services.report_projection_model import ProjectState


DATE = "2026-06-25"


def _session(key: str, aid: int, start: str, seconds: int, project_id: int = 1) -> dict:
    return {
        "row_kind": "project_session",
        "report_date": DATE,
        "projection_instance_key": key,
        "projection_kind": "base",
        "project_id": project_id,
        "project_name": f"P{project_id}",
        "project_description": "",
        "is_report_project": True,
        "is_report_classified": True,
        "is_report_uncategorized": False,
        "editable": True,
        "exportable": True,
        "is_in_progress": False,
        "member_slices": [{"report_date": DATE, "activity_id": aid, "slice_start_time": start}],
        "_projection_contributions": [
            {
                "report_date": DATE,
                "activity_id": aid,
                "slice_start_time": start,
                "duration_seconds": seconds,
                "activity_identity_key": f"activity:{aid}",
                "status": "normal",
            }
        ],
    }


def _member(aid: int, start: str) -> dict:
    return {"report_date": DATE, "activity_id": aid, "slice_start_time": start}


def _operation(op_id: int, kind: str, source: dict, **values) -> dict:
    return {
        "id": op_id,
        "report_date": DATE,
        "sequence": op_id,
        "operation_type": kind,
        "source_instance_key": source["projection_instance_key"],
        "source_expected_revision": source["projection_revision"],
        "payload": {"payload_version": engine.OPERATION_PAYLOAD_VERSION},
        "members": {"source": source["member_slices"]},
        **values,
    }


def _project(name: str = "P1", **changes) -> ProjectState:
    values = dict(
        project_id=1,
        project_name=name,
        project_description="description",
        is_deleted=False,
        is_archived=False,
        is_enabled=True,
        is_system=False,
        is_special=False,
        is_report_project=True,
        is_report_classified=True,
        is_report_uncategorized=False,
        is_official_project=True,
        report_attribution_kind="direct",
        project_key="project:1",
        report_project_key="project:1",
    )
    values.update(changes)
    return ProjectState(**values)


def test_replay_is_deterministic_and_does_not_modify_inputs():
    base = [_session("base:a", 1, f"{DATE} 09:00:00", 600)]
    prepared = engine.replay_operations(base, []).final_entries[0]
    operation = _operation(
        1,
        "edit_session",
        prepared,
        payload={
            "payload_version": engine.OPERATION_PAYLOAD_VERSION,
            "note": {"mode": "set", "value": "note"},
        },
    )
    before_base, before_operation = deepcopy(base), deepcopy(operation)
    first = engine.replay_operations(base, [operation])
    second = engine.replay_operations(base, [operation])
    assert first == second
    assert base == before_base
    assert operation == before_operation
    assert first.operation_diagnostics[0].state == engine.APPLIED


def test_project_presentation_changes_do_not_invalidate_durable_entry_revision():
    live = _session("base:a", 1, f"{DATE} 09:00:00", 10)
    live["is_in_progress"] = True
    first = engine.replay_operations([live], [], [_project()]).final_entries[0]
    live["_projection_contributions"][0]["duration_seconds"] = 999
    second = engine.replay_operations([live], [], [_project()]).final_entries[0]
    renamed = engine.replay_operations([live], [], [_project(name="Renamed")]).final_entries[0]
    archived = engine.replay_operations([live], [], [_project(is_archived=True)]).final_entries[0]
    assert first["projection_revision"] == second["projection_revision"]
    assert first["projection_revision"] == renamed["projection_revision"]
    assert first["projection_revision"] == archived["projection_revision"]
    assert renamed["project_name"] == "Renamed"
    assert archived["project_is_archived"] is True


def test_replay_result_records_are_recursively_immutable_and_deepcopy_safe():
    result = engine.replay_operations([_session("base:a", 1, f"{DATE} 09:00:00", 10)], [])
    copied = deepcopy(result)
    assert copied == result
    with pytest.raises(TypeError):
        result.final_entries[0]["project_name"] = "mutated"
    with pytest.raises(TypeError):
        result.final_entries[0]["member_slices"][0]["activity_id"] = 99


def test_merge_revalidates_adjacency_direction_and_revisions():
    base = [
        _session("base:left", 1, f"{DATE} 09:00:00", 600),
        _session("base:middle", 2, f"{DATE} 09:10:00", 600),
        _session("base:right", 3, f"{DATE} 09:20:00", 600),
    ]
    prepared = {row["projection_instance_key"]: row for row in engine.replay_operations(base, []).final_entries}
    invalid = _operation(
        1,
        "merge_sessions",
        prepared["base:left"],
        target_instance_key="base:right",
        target_expected_revision=prepared["base:right"]["projection_revision"],
        direction="next",
        members={"source": prepared["base:left"]["member_slices"], "target": prepared["base:right"]["member_slices"]},
    )
    result = engine.replay_operations(base, [invalid])
    assert result.operation_diagnostics[0].reason == "session_not_adjacent"
    assert len(result.final_entries) == 3
    invalid["target_instance_key"] = "base:middle"
    invalid["members"]["target"] = prepared["base:middle"]["member_slices"]
    invalid["target_expected_revision"] = "stale"
    result = engine.replay_operations(base, [invalid])
    assert result.operation_diagnostics[0].reason == "target_revision_conflict"


def test_strict_member_recovery_distinguishes_conflict_and_orphaned():
    base = [_session("base:current", 1, f"{DATE} 09:00:00", 600)]
    prepared = engine.replay_operations(base, []).final_entries[0]
    recovered = _operation(1, "hide_session", prepared)
    recovered["source_instance_key"] = "base:old-key"
    assert engine.replay_operations(base, [recovered]).operation_diagnostics[0].state == engine.APPLIED
    partial = deepcopy(recovered)
    partial["members"]["source"] = [*partial["members"]["source"], _member(2, f"{DATE} 09:10:00")]
    assert engine.replay_operations(base, [partial]).operation_diagnostics[0].state == engine.CONFLICT
    missing = deepcopy(recovered)
    missing["members"]["source"] = [_member(9, f"{DATE} 10:00:00")]
    assert engine.replay_operations(base, [missing]).operation_diagnostics[0].state == engine.ORPHANED


def test_split_supersedes_merge_and_all_descendants_without_virtual_entry():
    base = [
        _session("base:left", 1, f"{DATE} 09:00:00", 600),
        _session("base:right", 2, f"{DATE} 09:10:00", 600),
    ]
    prepared = {row["projection_instance_key"]: row for row in engine.replay_operations(base, []).final_entries}
    merge = _operation(
        1,
        "merge_sessions",
        prepared["base:left"],
        target_instance_key="base:right",
        target_expected_revision=prepared["base:right"]["projection_revision"],
        direction="next",
        members={"source": prepared["base:left"]["member_slices"], "target": prepared["base:right"]["member_slices"]},
    )
    merged = engine.replay_operations(base, [merge]).final_entries[0]
    edit = _operation(
        2,
        "edit_session",
        merged,
        payload={
            "payload_version": engine.OPERATION_PAYLOAD_VERSION,
            "note": {"mode": "set", "value": "descendant"},
        },
    )
    edited = engine.replay_operations(base, [merge, edit]).final_entries[0]
    split = _operation(3, "split_session", edited, undo_of_operation_id=1)
    result = engine.replay_operations(base, [merge, edit, split])
    assert [row["projection_instance_key"] for row in result.final_entries] == ["base:left", "base:right"]
    assert [item.state for item in result.operation_diagnostics] == [
        engine.SUPERSEDED_BY_UNDO,
        engine.SUPERSEDED_BY_UNDO,
        engine.APPLIED,
    ]


def test_repeated_merge_split_cycles_restore_simulated_inputs():
    base = [
        _session("base:a", 1, f"{DATE} 09:00:00", 600),
        _session("base:b", 2, f"{DATE} 09:10:00", 600),
        _session("base:c", 3, f"{DATE} 09:20:00", 600),
    ]
    prepared = {row["projection_instance_key"]: row for row in engine.replay_operations(base, []).final_entries}
    merge_ab = _operation(
        1,
        "merge_sessions",
        prepared["base:a"],
        target_instance_key="base:b",
        target_expected_revision=prepared["base:b"]["projection_revision"],
        direction="next",
        members={"source": prepared["base:a"]["member_slices"], "target": prepared["base:b"]["member_slices"]},
    )
    merged_ab = next(
        row for row in engine.replay_operations(base, [merge_ab]).final_entries
        if row["projection_instance_key"] == "merge:1"
    )
    split_ab = _operation(2, "split_session", merged_ab, undo_of_operation_id=1)
    restored = engine.replay_operations(base, [merge_ab, split_ab])
    restored_by_key = {row["projection_instance_key"]: row for row in restored.final_entries}
    merge_bc = _operation(
        3,
        "merge_sessions",
        restored_by_key["base:b"],
        target_instance_key="base:c",
        target_expected_revision=restored_by_key["base:c"]["projection_revision"],
        direction="next",
        members={"source": restored_by_key["base:b"]["member_slices"], "target": restored_by_key["base:c"]["member_slices"]},
    )
    merged_bc = next(
        row for row in engine.replay_operations(base, [merge_ab, split_ab, merge_bc]).final_entries
        if row["projection_instance_key"] == "merge:3"
    )
    split_bc = _operation(4, "split_session", merged_bc, undo_of_operation_id=3)
    result = engine.replay_operations(base, [merge_ab, split_ab, merge_bc, split_bc])
    assert [row["projection_instance_key"] for row in result.final_entries] == ["base:a", "base:b", "base:c"]
    assert [item.state for item in result.operation_diagnostics] == [
        engine.SUPERSEDED_BY_UNDO,
        engine.APPLIED,
        engine.SUPERSEDED_BY_UNDO,
        engine.APPLIED,
    ]


def test_invalid_edit_payload_is_diagnostic_only():
    base = [_session("base:a", 1, f"{DATE} 09:00:00", 600)]
    prepared = engine.replay_operations(base, []).final_entries[0]
    operation = _operation(1, "edit_session", prepared, payload={"payload_version": 999, "note": {"mode": "set", "value": "x"}})
    result = engine.replay_operations(base, [operation])
    assert result.operation_diagnostics[0].reason == "invalid_payload"
    assert "_applied_commands" not in result.final_entries[0]
