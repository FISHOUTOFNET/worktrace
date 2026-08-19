from __future__ import annotations

from worktrace.services.project_activity_summary_service import build_activity_summary_rows
from worktrace.services.statistics_file_projection import file_group_identity
from worktrace.services.view_model_service import _top3_activity_summary_labels


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


def test_automatic_summary_reuses_activity_detail_aggregate_order():
    rows = [
        {
            "activity_id": 1,
            "duration_seconds": 40,
            "activity_identity_key": "file:a",
            "activity_display_name": "A.docx",
        },
        {
            "activity_id": 2,
            "duration_seconds": 40,
            "activity_identity_key": "file:a",
            "activity_display_name": "A.docx",
        },
        {
            "activity_id": 3,
            "duration_seconds": 70,
            "activity_identity_key": "file:b",
            "activity_display_name": "B.xlsx",
        },
        {
            "activity_id": 4,
            "duration_seconds": 60,
            "activity_identity_key": "file:c",
            "activity_display_name": "C.pptx",
        },
        {
            "activity_id": 5,
            "duration_seconds": 50,
            "activity_identity_key": "file:d",
            "activity_display_name": "D.md",
        },
    ]

    assert _top3_activity_summary_labels(rows) == ["A.docx", "B.xlsx", "C.pptx"]


def test_file_statistics_key_keeps_same_display_name_distinct_by_resource_identity():
    first_key, first_name = file_group_identity(
        {
            "status": "normal",
            "resource_identity_key": "file:C:/Client-A/report.docx",
            "resource_display_name": "report.docx",
        }
    )
    second_key, second_name = file_group_identity(
        {
            "status": "normal",
            "resource_identity_key": "file:C:/Client-B/report.docx",
            "resource_display_name": "report.docx",
        }
    )

    assert first_name == second_name == "report.docx"
    assert first_key != second_key
