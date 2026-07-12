from __future__ import annotations

from worktrace.services.project_activity_summary_service import build_activity_summary_rows


def test_summary_groups_only_by_final_activity_identity_and_member_set():
    rows = [
        {
            "report_date": "2026-07-01", "activity_id": 1,
            "slice_start_time": "2026-07-01 09:00:00", "duration_seconds": 30,
            "activity_identity_key": "same", "report_project_id": 1,
            "report_project_name": "P1", "activity_display_name": "A",
        },
        {
            "report_date": "2026-07-01", "activity_id": 2,
            "slice_start_time": "2026-07-01 09:01:00", "duration_seconds": 30,
            "activity_identity_key": "same", "report_project_id": 2,
            "report_project_name": "P2", "activity_display_name": "A",
        },
    ]
    result = build_activity_summary_rows(rows, "2026-07-01", "base:x", "a" * 40)
    assert len(result) == 1
    assert result[0]["duration_seconds"] == 60
    assert result[0]["summary_id"]
