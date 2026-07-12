from __future__ import annotations

from worktrace.services.context_service import DERIVED_CONTEXT_SOURCES, ReportContextProjection


def test_context_sources_are_projection_only():
    assert DERIVED_CONTEXT_SOURCES == {
        "anchor_context", "same_project_context", "clipboard_transition_context"
    }


def test_context_projection_does_not_turn_derived_rows_into_anchors():
    rows = [
        {
            "id": 1, "start_time": "2026-07-04 09:00:00", "end_time": "2026-07-04 09:01:00",
            "status": "normal", "assignment_source": "anchor_context", "report_project_id": 7,
            "report_project_name": "P", "report_project_key": "project:7", "is_report_project": True,
        },
        {
            "id": 2, "start_time": "2026-07-04 09:01:00", "end_time": "2026-07-04 09:02:00",
            "status": "normal", "assignment_source": "uncategorized", "is_report_project": False,
        },
    ]
    projection = ReportContextProjection.build(rows, carry_minutes=15)
    assert projection.rows[1]["is_report_project"] is False
