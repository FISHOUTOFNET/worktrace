from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.services import project_service, view_model_service
from worktrace.services.activity_display_projection import (
    build_aggregate_live_clock,
    build_kpi_live_targets,
)
from worktrace.services.view_model_service import (
    get_overview_view_model,
    get_timeline_view_model,
)

pytestmark = [pytest.mark.db, pytest.mark.contract]


def _closed(
    *,
    day: str,
    start: str,
    end: str,
    status: str = "normal",
    project_id: int | None = None,
    title: str = "item.txt",
) -> int:
    activity_id = activity_service.create_activity(
        "Editor",
        "editor.exe",
        title,
        status=status,
        project_id=project_id,
        start_time=f"{day} {start}",
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.close_activity(activity_id, f"{day} {end}")
    return activity_id


def _segment_seconds(model: dict) -> int:
    return sum(
        int(segment.get("duration_seconds") or 0)
        for segment in model["project_distribution"]["segments"]
    )


def test_attributed_excluded_time_counts_without_becoming_recent(temp_db):
    day = "2026-07-22"
    project_id = project_service.create_project("Private client")
    _closed(
        day=day,
        start="09:00:00",
        end="09:30:00",
        status="excluded",
        project_id=project_id,
    )

    overview = get_overview_view_model(day)
    timeline = get_timeline_view_model(day)

    assert overview["recent"] == []
    assert overview["today_total_seconds"] == timeline["total_seconds"] == 1800
    assert overview["project_distribution"]["total_seconds"] == 1800
    assert _segment_seconds(overview) == 1800
    assert overview["project_distribution"]["segments"][0]["key"] == f"project:{project_id}"


def test_standalone_excluded_time_is_privacy_safe_other_in_total_breakdown(temp_db):
    day = "2026-07-22"
    _closed(
        day=day,
        start="10:00:00",
        end="10:20:00",
        status="excluded",
        title="secret.txt",
    )

    overview = get_overview_view_model(day)
    timeline = get_timeline_view_model(day)

    assert overview["recent"] == []
    assert overview["today_total_seconds"] == timeline["total_seconds"] == 1200
    assert overview["project_distribution"]["total_seconds"] == 1200
    assert _segment_seconds(overview) == 1200
    segment = overview["project_distribution"]["segments"][0]
    assert segment["key"] == "other"
    assert segment["label"] == "其他"
    assert "已排除" not in str(overview["project_distribution"])


def test_recent_limit_does_not_limit_overview_accounting_or_kpi_input(temp_db, monkeypatch):
    day = "2026-07-22"
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    count = view_model_service._RECENT_LIMIT + 2

    for index in range(count):
        start_minute = index * 10
        end_minute = start_minute + 10
        _closed(
            day=day,
            start=f"{8 + start_minute // 60:02d}:{start_minute % 60:02d}:00",
            end=f"{8 + end_minute // 60:02d}:{end_minute % 60:02d}:00",
            project_id=project_a if index % 2 == 0 else project_b,
            title=f"item-{index}.txt",
        )

    captured: dict[str, int] = {}
    original = view_model_service.build_kpi_live_targets

    def capture(rows, live_clock):
        captured["row_count"] = len(rows)
        return original(rows, live_clock)

    monkeypatch.setattr(view_model_service, "build_kpi_live_targets", capture)
    overview = get_overview_view_model(day)

    expected = count * 10 * 60
    assert len(overview["recent"]) == view_model_service._RECENT_LIMIT
    assert captured["row_count"] == count
    assert overview["today_total_seconds"] == expected
    assert overview["project_distribution"]["total_seconds"] == expected
    assert _segment_seconds(overview) == expected


def test_aggregate_live_clock_uses_complete_reporting_subset():
    source_clock = {
        "sampled_at_epoch_ms": 100_000,
        "started_at_epoch_ms": 10_000,
        "elapsed_seconds_at_sample": 120,
        "aggregate_base_seconds": 600,
        "duration_semantic": "aggregate_live",
        "is_live": True,
        "live_state": "persisted_open",
        "display_span_id": "span-1",
        "stable_live_key_hash": "live-1",
    }
    rows = [
        {
            "duration_seconds": 600,
            "is_classified": True,
            "is_uncategorized": False,
            "contributes_to_totals": True,
        }
        for _ in range(21)
    ]
    rows.append(
        {
            "duration_seconds": 720,
            "is_classified": True,
            "is_uncategorized": False,
            "contributes_to_totals": True,
            "live_clock": source_clock,
        }
    )
    rows.append(
        {
            "duration_seconds": 999,
            "is_classified": True,
            "is_uncategorized": False,
            "contributes_to_totals": False,
            "live_clock": source_clock,
        }
    )

    clock = build_aggregate_live_clock(rows)
    assert clock is not None
    assert clock["elapsed_seconds_at_sample"] == 120
    assert clock["aggregate_base_seconds"] == 22 * 600

    target = build_kpi_live_targets(rows, {})["today_total_seconds"]
    assert target["enabled"] is True
    assert target["live_clock"] == clock
