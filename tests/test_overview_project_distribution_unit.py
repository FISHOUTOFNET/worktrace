from __future__ import annotations

import pytest

from worktrace.services.view_model_service import (
    _accumulate_overview_distribution_bucket,
    _finalize_overview_project_distribution,
    _session_display_seconds,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _project(
    project_id: int,
    label: str,
    duration_seconds: int,
    *,
    adjusted_duration_seconds: int | None = None,
    contributes_to_totals: bool = True,
) -> dict:
    return {
        "report_project_id": project_id,
        "project_id": project_id,
        "project_name": label,
        "duration_seconds": duration_seconds,
        "adjusted_duration_seconds": adjusted_duration_seconds,
        "contributes_to_totals": contributes_to_totals,
        "is_report_project": True,
        "is_report_uncategorized": False,
    }


def _uncategorized(
    duration_seconds: int,
    *,
    adjusted_duration_seconds: int | None = None,
) -> dict:
    return {
        "project_id": 0,
        "project_name": "未归类",
        "duration_seconds": duration_seconds,
        "adjusted_duration_seconds": adjusted_duration_seconds,
        "contributes_to_totals": True,
        "is_report_project": False,
        "is_report_uncategorized": True,
    }


def _distribution(*sessions: dict) -> dict:
    buckets: dict[str, dict] = {}
    for session in sessions:
        _accumulate_overview_distribution_bucket(
            buckets,
            session,
            _session_display_seconds(session),
        )
    return _finalize_overview_project_distribution(buckets)


def test_same_project_and_uncategorized_sessions_are_each_merged() -> None:
    result = _distribution(
        _project(7, "WorkTrace", 1200),
        _uncategorized(300),
        _project(7, "WorkTrace", 600),
        _uncategorized(900),
    )

    assert result["total_seconds"] == 3000
    assert result["segments"] == [
        {
            "key": "project:7",
            "project_id": 7,
            "label": "WorkTrace",
            "duration_seconds": 1800,
            "is_uncategorized": False,
            "is_other": False,
        },
        {
            "key": "uncategorized",
            "project_id": None,
            "label": "未归类",
            "duration_seconds": 1200,
            "is_uncategorized": True,
            "is_other": False,
        },
    ]


@pytest.mark.parametrize(
    ("category_count", "expected_keys", "other_count"),
    [
        (1, ["project:1"], None),
        (3, ["project:1", "project:2", "project:3"], None),
        (4, ["project:1", "project:2", "project:3", "other"], 1),
        (6, ["project:1", "project:2", "project:3", "other"], 3),
    ],
)
def test_top_three_and_other_boundaries(
    category_count: int,
    expected_keys: list[str],
    other_count: int | None,
) -> None:
    sessions = [
        _project(index, f"P{index}", (category_count - index + 1) * 100)
        for index in range(1, category_count + 1)
    ]
    result = _distribution(*sessions)

    assert [segment["key"] for segment in result["segments"]] == expected_keys
    if other_count is None:
        assert all(segment["is_other"] is False for segment in result["segments"])
    else:
        other = result["segments"][-1]
        assert other["category_count"] == other_count
        assert other["duration_seconds"] == sum(
            session["duration_seconds"] for session in sessions[3:]
        )


def test_uncategorized_uses_the_same_ranking_rules_as_projects() -> None:
    top_three = _distribution(
        _project(1, "A", 500),
        _uncategorized(900),
        _project(2, "B", 700),
        _project(3, "C", 300),
    )
    assert [segment["key"] for segment in top_three["segments"]] == [
        "uncategorized",
        "project:2",
        "project:1",
        "other",
    ]

    in_other = _distribution(
        _project(1, "A", 900),
        _project(2, "B", 800),
        _project(3, "C", 700),
        _uncategorized(100),
        _project(4, "D", 200),
    )
    assert [segment["key"] for segment in in_other["segments"]] == [
        "project:1",
        "project:2",
        "project:3",
        "other",
    ]
    assert in_other["segments"][-1]["duration_seconds"] == 300
    assert in_other["segments"][-1]["category_count"] == 2


def test_adjusted_duration_exclusions_zero_and_unknown_categories() -> None:
    result = _distribution(
        _project(1, "Adjusted", 100, adjusted_duration_seconds=450),
        _project(2, "Excluded", 600, contributes_to_totals=False),
        _project(3, "Zero", 0),
        {
            "duration_seconds": 700,
            "contributes_to_totals": True,
            "is_report_project": False,
            "is_report_uncategorized": False,
        },
    )

    assert result["total_seconds"] == 450
    assert [segment["key"] for segment in result["segments"]] == ["project:1"]
    assert result["segments"][0]["duration_seconds"] == 450


def test_equal_durations_use_stable_category_key_order() -> None:
    result = _distribution(
        _uncategorized(600),
        _project(2, "Two", 600),
        _project(10, "Ten", 600),
        _project(1, "One", 600),
    )

    assert [segment["key"] for segment in result["segments"]] == [
        "project:1",
        "project:10",
        "project:2",
        "other",
    ]
    assert result["segments"][-1]["duration_seconds"] == 600
    assert result["segments"][-1]["category_count"] == 1
