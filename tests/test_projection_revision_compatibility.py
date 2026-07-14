from __future__ import annotations

import pytest

from worktrace.services import report_session_operation_engine as engine
from worktrace.services.report_projection_identity import legacy_projection_revision
from worktrace.services.report_projection_model import ProjectState


pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]
DATE = "2026-07-03"


def _project(name: str) -> ProjectState:
    return ProjectState(
        project_id=1,
        project_name=name,
        project_description="legacy description",
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


def _base_session() -> dict:
    start = f"{DATE} 09:00:00"
    return {
        "row_kind": "project_session",
        "report_date": DATE,
        "projection_instance_key": "base:legacy",
        "projection_kind": "base",
        "project_id": 1,
        "project_name": "Original",
        "project_description": "legacy description",
        "is_report_project": True,
        "is_report_classified": True,
        "is_report_uncategorized": False,
        "is_official_project": True,
        "report_attribution_kind": "direct",
        "project_key": "project:1",
        "report_project_key": "project:1",
        "editable": True,
        "exportable": True,
        "is_in_progress": False,
        "member_slices": [
            {"report_date": DATE, "activity_id": 1, "slice_start_time": start}
        ],
        "_projection_contributions": [
            {
                "report_date": DATE,
                "activity_id": 1,
                "slice_start_time": start,
                "duration_seconds": 600,
                "activity_identity_key": "activity:1",
                "display_project_id": 1,
                "report_project_id": 1,
                "status": "normal",
            }
        ],
    }


def test_existing_v4_revision_replays_after_durable_revision_cutover():
    project = _project("Original")
    prepared = engine.replay_operations([_base_session()], [], [project]).final_entries[0]
    old_revision = legacy_projection_revision(prepared, project_state=project)
    assert old_revision != prepared["projection_revision"]

    operation = {
        "id": 1,
        "report_date": DATE,
        "sequence": 1,
        "operation_type": "edit_session",
        "source_instance_key": prepared["projection_instance_key"],
        "source_expected_revision": old_revision,
        "payload": {
            "payload_version": engine.OPERATION_PAYLOAD_VERSION,
            "note": {"mode": "set", "value": "legacy survives"},
        },
        "members": {"source": prepared["member_slices"]},
    }

    replayed = engine.replay_operations([_base_session()], [operation], [_project("Renamed")])
    assert replayed.operation_diagnostics[0].state == engine.APPLIED
    assert replayed.final_entries[0]["project_name"] == "Renamed"
    assert replayed.final_entries[0]["session_note"] == "legacy survives"
