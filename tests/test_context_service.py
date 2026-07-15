from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from worktrace.constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE
from worktrace.services.context_service import ReportContextProjection


def _row(
    aid: int,
    start: str,
    *,
    seconds: int = 30,
    project_id: int = 0,
    source: str = "uncategorized",
    status: str = "normal",
    deleted: bool = False,
) -> dict:
    start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    end = (start_dt + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    project = project_id > 0 and not deleted
    return {
        "id": aid,
        "start_time": start,
        "end_time": end,
        "duration_seconds": seconds,
        "report_duration_seconds": seconds,
        "status": status,
        "assignment_source": source,
        "effective_project_id": project_id or None,
        "effective_project_is_deleted": deleted,
        "report_project_id": project_id,
        "report_project_name": f"P{project_id}" if project else "未归类",
        "report_project_key": (
            f"project:{project_id}" if project else "uncategorized:1"
        ),
        "report_project_is_deleted": deleted,
        "is_report_project": project,
        "is_report_classified": project,
        "is_report_uncategorized": not project,
        "is_official_project": project
        and source in {"manual", "keyword_rule", "folder_rule"},
        "report_attribution_kind": "official_direct" if project else "none",
    }


def test_report_context_projection_is_pure_and_deterministic():
    rows = [
        _row(1, "2026-07-01 09:00:00", project_id=7, source="manual"),
        _row(2, "2026-07-01 09:01:00"),
        _row(
            3,
            "2026-07-01 09:02:00",
            project_id=7,
            source="keyword_rule",
        ),
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
    assert copied.rows[1]["report_attribution_kind"] == (
        "clipboard_transition_context"
    )

    blocked = ReportContextProjection.build(
        rows,
        carry_minutes=15,
        boundary_times=["2026-07-01 09:00:45"],
        clipboard_times={1: ["2026-07-01 09:00:50"]},
    )
    assert blocked.rows[1]["is_report_project"] is False


@pytest.mark.parametrize("status", [STATUS_IDLE, STATUS_ERROR, STATUS_EXCLUDED])
def test_short_special_status_is_attributed_between_matching_projects(
    status: str,
):
    result = ReportContextProjection.build(
        [
            _row(
                1,
                "2026-07-01 09:00:00",
                seconds=60,
                project_id=7,
                source="manual",
            ),
            _row(
                2,
                "2026-07-01 09:01:00",
                seconds=10 * 60,
                status=status,
            ),
            _row(
                3,
                "2026-07-01 09:11:00",
                seconds=60,
                project_id=7,
                source="folder_rule",
            ),
        ],
        carry_minutes=15,
    )
    assert result.rows[1]["report_project_id"] == 7
    assert result.rows[1]["is_report_project"] is True
    assert result.rows[1]["is_official_project"] is False


@pytest.mark.parametrize("status", [STATUS_IDLE, STATUS_ERROR, STATUS_EXCLUDED])
def test_direct_special_status_preserves_own_project_and_blocks_previous_context(
    status: str,
):
    result = ReportContextProjection.build(
        [
            _row(
                1,
                "2026-07-01 09:00:00",
                seconds=60,
                project_id=7,
                source="manual",
            ),
            _row(
                2,
                "2026-07-01 09:01:00",
                seconds=60,
                project_id=8,
                source="folder_rule",
                status=status,
            ),
            _row(3, "2026-07-01 09:02:00", seconds=30),
        ],
        carry_minutes=15,
    )
    assert result.rows[1]["report_project_id"] == 8
    assert result.rows[1]["report_attribution_kind"] == "official_direct"
    assert result.rows[2]["is_report_project"] is False
    assert all(item.activity_id != 2 for item in result.attributions)


def test_deleted_direct_project_remains_context_barrier():
    result = ReportContextProjection.build(
        [
            _row(1, "2026-07-01 09:00:00", project_id=7, source="manual"),
            _row(
                2,
                "2026-07-01 09:01:00",
                project_id=8,
                source="manual",
                status=STATUS_IDLE,
                deleted=True,
            ),
            _row(3, "2026-07-01 09:01:30"),
        ],
        carry_minutes=15,
    )
    assert result.rows[1]["is_report_project"] is False
    assert result.rows[2]["is_report_project"] is False


@pytest.mark.parametrize("status", [STATUS_IDLE, STATUS_ERROR, STATUS_EXCLUDED])
def test_special_status_over_context_limit_is_not_attributed(status: str):
    result = ReportContextProjection.build(
        [
            _row(
                1,
                "2026-07-01 09:00:00",
                seconds=60,
                project_id=7,
                source="manual",
            ),
            _row(
                2,
                "2026-07-01 09:01:00",
                seconds=16 * 60,
                status=status,
            ),
            _row(
                3,
                "2026-07-01 09:17:00",
                seconds=60,
                project_id=7,
                source="folder_rule",
            ),
        ],
        carry_minutes=15,
    )
    assert result.rows[1]["is_report_project"] is False
    assert result.attributions == ()


def test_following_anchor_uses_target_start_and_does_not_charge_anchor_duration():
    result = ReportContextProjection.build(
        [
            _row(
                1,
                "2026-07-01 09:00:00",
                seconds=10 * 60,
                status=STATUS_IDLE,
            ),
            _row(
                2,
                "2026-07-01 09:10:00",
                seconds=60 * 60,
                project_id=7,
                source="manual",
            ),
        ],
        carry_minutes=15,
    )
    assert result.rows[0]["report_project_id"] == 7


def test_long_special_status_blocks_context_propagation():
    for status in (STATUS_IDLE, STATUS_ERROR, STATUS_EXCLUDED):
        result = ReportContextProjection.build(
            [
                _row(
                    1,
                    "2026-07-01 09:00:00",
                    seconds=60,
                    project_id=7,
                    source="manual",
                ),
                _row(
                    2,
                    "2026-07-01 09:01:00",
                    seconds=16 * 60,
                    status=status,
                ),
                _row(3, "2026-07-01 09:17:00", seconds=30),
            ],
            carry_minutes=15,
        )
        assert result.rows[2]["is_report_project"] is False
