from __future__ import annotations

from copy import deepcopy

from worktrace.services.context_service import ReportContextProjection


def _row(aid: int, start: str, *, project_id: int = 0, source: str = "uncategorized", status: str = "normal") -> dict:
    end = start[:-2] + "30"
    project = project_id > 0
    return {
        "id": aid,
        "start_time": start,
        "end_time": end,
        "status": status,
        "assignment_source": source,
        "report_project_id": project_id,
        "report_project_name": f"P{project_id}" if project else "未归类",
        "report_project_key": f"project:{project_id}" if project else "uncategorized:1",
        "is_report_project": project,
        "is_report_classified": project,
        "is_report_uncategorized": not project,
    }


def test_report_context_projection_is_pure_and_deterministic():
    rows = [
        _row(1, "2026-07-01 09:00:00", project_id=7, source="manual"),
        _row(2, "2026-07-01 09:01:00"),
        _row(3, "2026-07-01 09:02:00", project_id=7, source="keyword_rule"),
    ]
    original = deepcopy(rows)
    first = ReportContextProjection.build(rows, carry_minutes=15)
    second = ReportContextProjection.build(rows, carry_minutes=15)
    assert rows == original
    assert first.rows == second.rows
    assert first.rows[1]["report_project_id"] == 7
    assert first.attributions[0].attribution_kind == "same_project_context"


def test_conflicting_anchors_do_not_attribute():
    result = ReportContextProjection.build(
        [
            _row(1, "2026-07-01 09:00:00", project_id=7, source="manual"),
            _row(2, "2026-07-01 09:01:00"),
            _row(3, "2026-07-01 09:02:00", project_id=8, source="manual"),
        ],
        carry_minutes=15,
    )
    assert result.rows[1]["is_report_project"] is False
    assert result.attributions == ()


def test_clipboard_transition_and_hard_boundary_policy():
    rows = [
        _row(1, "2026-07-01 09:00:00", project_id=7, source="manual"),
        _row(2, "2026-07-01 09:01:00"),
    ]
    copied = ReportContextProjection.build(
        rows,
        carry_minutes=0,
        clipboard_times={1: ["2026-07-01 09:00:50"]},
    )
    assert copied.rows[1]["report_attribution_kind"] == "clipboard_transition_context"

    blocked = ReportContextProjection.build(
        rows,
        carry_minutes=15,
        boundary_times=["2026-07-01 09:00:45"],
        clipboard_times={1: ["2026-07-01 09:00:50"]},
    )
    assert blocked.rows[1]["is_report_project"] is False
