from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from worktrace.services.context_service import ReportContextProjection
from worktrace.services.report_project_transition_projection import (
    REPORT_PROJECT_CONFIRM_SECONDS,
    REPORT_SAME_PROJECT_DETOUR_SECONDS,
    REPORT_UNCATEGORIZED_GRACE_SECONDS,
    ReportProjectTransitionProjection,
)


def _row(
    aid: int,
    start: str,
    *,
    seconds: int,
    project_id: int | None = None,
    source: str = "uncategorized",
    status: str = "normal",
) -> dict:
    start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    end = (start_dt + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
    project = project_id is not None
    report_project_id = int(project_id or 1)
    return {
        "id": aid,
        "start_time": start,
        "end_time": end,
        "duration_seconds": seconds,
        "report_duration_seconds": seconds,
        "status": status,
        "assignment_source": source,
        "effective_project_id": report_project_id,
        "effective_project_name": f"P{project_id}" if project else "未归类",
        "effective_project_description": "",
        "effective_project_is_deleted": False,
        "effective_project_is_archived": False,
        "report_project_id": report_project_id,
        "report_project_name": f"P{project_id}" if project else "未归类",
        "report_project_description": "",
        "report_project_key": (
            f"project:{project_id}" if project else "uncategorized:1"
        ),
        "report_project_is_deleted": False,
        "report_project_is_archived": False,
        "is_report_project": project,
        "is_report_classified": project,
        "is_report_uncategorized": not project,
        "is_official_project": project
        and source in {"manual", "keyword_rule", "folder_rule"},
        "report_attribution_kind": "official_direct" if project else "none",
    }


def _project_ids(result: ReportProjectTransitionProjection) -> list[int]:
    return [int(row.get("report_project_id") or 0) for row in result.rows]


def test_policy_thresholds_are_small_report_only_defaults():
    assert REPORT_PROJECT_CONFIRM_SECONDS == 8
    assert REPORT_UNCATEGORIZED_GRACE_SECONDS == 30
    assert REPORT_SAME_PROJECT_DETOUR_SECONDS == 20


def test_projection_is_pure_and_deterministic():
    rows = [
        _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
        _row(2, "2026-08-13 09:01:00", seconds=3, project_id=8, source="folder_rule"),
        _row(3, "2026-08-13 09:01:03", seconds=60, project_id=7, source="folder_rule"),
    ]
    original = deepcopy(rows)
    first = ReportProjectTransitionProjection.build(rows)
    second = ReportProjectTransitionProjection.build(rows)
    assert rows == original
    assert first == second
    assert _project_ids(first) == [7, 7, 7]


def test_short_same_project_detour_is_absorbed():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(2, "2026-08-13 09:01:00", seconds=12, project_id=8, source="keyword_rule"),
            _row(3, "2026-08-13 09:01:12", seconds=60, project_id=7, source="folder_rule"),
        ]
    )
    assert _project_ids(result) == [7, 7, 7]
    assert result.rows[1]["report_attribution_kind"] == (
        "report_transition_same_project_detour"
    )
    assert result.rows[1]["effective_project_id"] == 8
    assert result.rows[1]["assignment_source"] == "keyword_rule"
    assert result.rows[1]["is_official_project"] is False


def test_same_project_detour_over_twenty_seconds_remains_visible():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(2, "2026-08-13 09:01:00", seconds=21, project_id=8, source="folder_rule"),
            _row(3, "2026-08-13 09:01:21", seconds=60, project_id=7, source="folder_rule"),
        ]
    )
    assert _project_ids(result) == [7, 8, 7]


def test_unconfirmed_new_project_is_carried_by_previous_stable_project():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(2, "2026-08-13 09:01:00", seconds=7, project_id=8, source="folder_rule"),
            _row(3, "2026-08-13 09:01:07", seconds=60, project_id=9, source="folder_rule"),
        ]
    )
    assert _project_ids(result) == [7, 7, 9]
    assert result.rows[1]["report_attribution_kind"] == (
        "report_transition_pending_project"
    )


def test_project_switch_at_confirmation_threshold_is_backdated_and_kept():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(2, "2026-08-13 09:01:00", seconds=8, project_id=8, source="folder_rule"),
            _row(3, "2026-08-13 09:01:08", seconds=60, project_id=9, source="folder_rule"),
        ]
    )
    assert _project_ids(result) == [7, 8, 9]
    assert result.rows[1]["start_time"] == "2026-08-13 09:01:00"


def test_short_uncategorized_transition_stays_with_previous_project():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(2, "2026-08-13 09:01:00", seconds=29),
            _row(3, "2026-08-13 09:01:29", seconds=60, project_id=8, source="folder_rule"),
        ]
    )
    assert _project_ids(result) == [7, 7, 8]
    assert result.rows[1]["report_attribution_kind"] == (
        "report_transition_uncategorized_grace"
    )


def test_uncategorized_transition_at_thirty_seconds_remains_uncategorized():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(2, "2026-08-13 09:01:00", seconds=30),
            _row(3, "2026-08-13 09:01:30", seconds=60, project_id=8, source="folder_rule"),
        ]
    )
    assert _project_ids(result) == [7, 1, 8]
    assert result.rows[1]["is_report_uncategorized"] is True


def test_manual_assignment_is_authoritative_and_blocks_smoothing_across_it():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(2, "2026-08-13 09:01:00", seconds=2, project_id=8, source="manual"),
            _row(3, "2026-08-13 09:01:02", seconds=3, project_id=7, source="folder_rule"),
        ]
    )
    assert _project_ids(result) == [7, 8, 7]
    assert result.rows[1]["report_attribution_kind"] == "official_direct"


def test_explicit_boundary_blocks_same_project_detour_absorption():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(2, "2026-08-13 09:01:00", seconds=5, project_id=8, source="folder_rule"),
            _row(3, "2026-08-13 09:01:05", seconds=60, project_id=7, source="folder_rule"),
        ],
        boundary_times=["2026-08-13 09:01:05"],
    )
    assert _project_ids(result) == [7, 8, 7]


def test_non_normal_direct_row_is_not_smoothed():
    result = ReportProjectTransitionProjection.build(
        [
            _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
            _row(
                2,
                "2026-08-13 09:01:00",
                seconds=3,
                project_id=8,
                source="folder_rule",
                status="idle",
            ),
            _row(3, "2026-08-13 09:01:03", seconds=60, project_id=7, source="folder_rule"),
        ]
    )
    assert _project_ids(result) == [7, 8, 7]


def test_short_uncategorized_transition_survives_conflicting_context_anchors():
    rows = [
        _row(1, "2026-08-13 09:00:00", seconds=60, project_id=7, source="folder_rule"),
        _row(2, "2026-08-13 09:01:00", seconds=5),
        _row(3, "2026-08-13 09:01:05", seconds=60, project_id=8, source="folder_rule"),
    ]
    smoothed = ReportProjectTransitionProjection.build(rows).rows
    context = ReportContextProjection.build(smoothed, carry_minutes=15)
    assert int(context.rows[1]["report_project_id"]) == 7
    assert context.rows[1]["is_report_project"] is True


def test_transition_policy_is_wired_before_context_and_not_into_collector():
    root = Path(__file__).resolve().parents[1]
    fact_query = (root / "worktrace/services/report_fact_query_service.py").read_text(
        encoding="utf-8"
    )
    assert fact_query.index('stage("project_transition_projection")') < fact_query.index(
        'stage("context_projection")'
    )

    collector_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "worktrace/collector").rglob("*.py"))
    )
    ownership_source = (
        root / "worktrace/services/project_ownership_service.py"
    ).read_text(encoding="utf-8")
    assert "ReportProjectTransitionProjection" not in collector_source
    assert "REPORT_PROJECT_CONFIRM_SECONDS" not in collector_source
    assert "ReportProjectTransitionProjection" not in ownership_source
