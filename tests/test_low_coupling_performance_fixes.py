from __future__ import annotations

from pathlib import Path

from worktrace.services import project_activity_summary_service


def test_lightweight_top_activity_labels_match_full_summary_ranking():
    rows = [
        {
            "resource_identity_key": "file:a",
            "resource_display_name": "A.docx",
            "activity_display_name": "A.docx",
            "app_name": "Word",
            "duration_seconds": 40,
        },
        {
            "resource_identity_key": "file:b",
            "resource_display_name": "B.xlsx",
            "activity_display_name": "B.xlsx",
            "app_name": "Excel",
            "duration_seconds": 60,
        },
        {
            "resource_identity_key": "file:a",
            "resource_display_name": "A.docx",
            "activity_display_name": "A.docx",
            "app_name": "Word",
            "duration_seconds": 20,
        },
        {
            "resource_identity_key": "file:c",
            "resource_display_name": "C.pptx",
            "activity_display_name": "C.pptx",
            "app_name": "PowerPoint",
            "duration_seconds": 15,
        },
        {
            "resource_identity_key": "file:d",
            "resource_display_name": "D.txt",
            "activity_display_name": "D.txt",
            "app_name": "Editor",
            "duration_seconds": 5,
        },
    ]
    full = project_activity_summary_service.build_activity_summary_rows(
        rows,
        report_date="2026-08-22",
        scope_key="session",
        projection_revision="revision",
    )
    expected = [str(item.get("activity_name") or "") for item in full[:3]]
    assert project_activity_summary_service.build_top_activity_labels(rows, limit=3) == expected


def test_navigation_performance_fix_contracts_remain_local():
    root = Path(__file__).resolve().parents[1]
    init = (root / "worktrace/webview_ui/js/init_fd_work_v5.js").read_text(encoding="utf-8")
    lifecycle = (root / "worktrace/webview_ui/js/page_lifecycle.js").read_text(encoding="utf-8")
    timeline = (root / "worktrace/webview_ui/js/timeline.js").read_text(encoding="utf-8")
    view_model = (root / "worktrace/services/view_model_service.py").read_text(encoding="utf-8")
    report_as_of = (root / "worktrace/services/report_as_of_snapshot_service.py").read_text(encoding="utf-8")

    assert 'preservePresentation: pageId === "statistics"' in init
    assert '"timeline-navigation"' in timeline
    assert 'App.requestCoordinator.share(' in timeline
    assert 'var loadedDate = String(App.lastTimelineData.date || "");' in lifecycle
    assert "build_top_activity_labels(" in view_model

    statistics_overlay = report_as_of.split(
        "def build_statistics_as_of_snapshot", 1
    )[1]
    before_open_activity = statistics_overlay.split(
        "open_activity_id = context.verified_open_activity_id", 1
    )[0]
    assert "snapshot_seconds_for_date_range(" in before_open_activity
    assert "start_date" in before_open_activity
    assert "end_date" in before_open_activity
