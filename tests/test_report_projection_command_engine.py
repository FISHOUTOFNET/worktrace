from __future__ import annotations

from worktrace.services import report_session_operation_engine as engine


def _session(key: str, aid: int, start: str, seconds: int, project_id: int = 1) -> dict:
    return {
        "row_kind": "project_session",
        "report_date": "2026-06-25",
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
        "member_slices": [
            {
                "report_date": "2026-06-25",
                "activity_id": aid,
                "slice_start_time": start,
                "slice_end_time": "2026-06-25 09:10:00",
            }
        ],
        "_projection_contributions": [
            {
                "report_date": "2026-06-25",
                "activity_id": aid,
                "slice_start_time": start,
                "slice_end_time": "2026-06-25 09:10:00",
                "duration_seconds": seconds,
                "activity_identity_key": f"activity:{aid}",
                "status": "normal",
            }
        ],
    }


def _edit(op_id: int, key: str, payload: dict) -> dict:
    return {
        "id": op_id,
        "replay_order": op_id,
        "operation_type": "edit_session",
        "base_instance_key": key,
        "match_state": "active",
        "payload": {"payload_version": 1, **payload},
    }


def test_duration_override_then_hide_activity_allocates_from_projected_contribution():
    session = _session("base:a", 1, "2026-06-25 09:00:00", 600)
    session["member_slices"].append(
        {
            "report_date": "2026-06-25",
            "activity_id": 2,
            "slice_start_time": "2026-06-25 09:10:00",
            "slice_end_time": "2026-06-25 09:20:00",
        }
    )
    session["_projection_contributions"].append(
        {
            "report_date": "2026-06-25",
            "activity_id": 2,
            "slice_start_time": "2026-06-25 09:10:00",
            "slice_end_time": "2026-06-25 09:20:00",
            "duration_seconds": 600,
            "activity_identity_key": "activity:2",
            "status": "normal",
        }
    )
    result = engine.apply_operations(
        [session],
        [
            _edit(1, "base:a", {"duration": {"mode": "set", "value": 600}}),
            {
                "id": 2,
                "replay_order": 2,
                "operation_type": "hide_activity",
                "base_instance_key": "base:a",
                "match_state": "active",
                "members": {
                    "hidden_activity": [
                        {
                            "report_date": "2026-06-25",
                            "activity_id": 1,
                            "slice_start_time": "2026-06-25 09:00:00",
                            "slice_end_time": "2026-06-25 09:10:00",
                        }
                    ]
                },
            },
        ],
    )

    assert len(result) == 1
    assert result[0]["duration_seconds"] == 300
    assert sum(row["duration_seconds"] for row in engine.build_projected_activity_contributions(result)) == 300


def test_copy_edit_does_not_change_origin_and_merge_edit_is_independent():
    left = _session("base:left", 1, "2026-06-25 09:00:00", 600, project_id=1)
    right = _session("base:right", 2, "2026-06-25 09:10:00", 600, project_id=2)
    result = engine.apply_operations(
        [left, right],
        [
            {"id": 1, "replay_order": 1, "operation_type": "copy_session", "base_instance_key": "base:left", "match_state": "active"},
            _edit(2, "copy:1", {"note": {"mode": "set", "value": "copy note"}}),
            {
                "id": 3,
                "replay_order": 3,
                "operation_type": "merge_sessions",
                "base_instance_key": "base:left",
                "target_instance_key": "base:right",
                "operation_group_key": "g1",
                "match_state": "active",
            },
            _edit(4, "merge:g1", {"duration": {"mode": "set", "value": 900}}),
        ],
    )

    by_key = {row["projection_instance_key"]: row for row in result}
    assert by_key["copy:1"]["session_note"] == "copy note"
    assert by_key["merge:g1"]["duration_seconds"] == 900
    assert "base:left" not in by_key
    assert sum(row["duration_seconds"] for row in engine.build_projected_activity_contributions([by_key["merge:g1"]])) == 900
