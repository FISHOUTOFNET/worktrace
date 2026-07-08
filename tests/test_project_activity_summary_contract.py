from __future__ import annotations

import pytest

from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.services import (
    project_activity_summary_service,
    timeline_service,
    view_model_service,
)

pytestmark = [pytest.mark.contract]


def _row(
    activity_id: int,
    *,
    identity: str,
    seconds: int,
    report_project_id: int,
    report_project_name: str,
    display_project_id: int = 0,
    display_project_name: str = UNCATEGORIZED_PROJECT,
    title: str = "Same title",
    candidate: str = "",
    in_progress: bool = False,
) -> dict:
    return {
        "id": activity_id,
        "activity_identity_key": identity,
        "resource_identity_key": identity,
        "activity_display_name": title,
        "resource_display_name": title,
        "app_name": "App",
        "report_duration_seconds": seconds,
        "duration_seconds": seconds,
        "report_project_id": report_project_id,
        "report_project_name": report_project_name,
        "report_project_description": "",
        "display_project_id": display_project_id,
        "display_project_name": display_project_name,
        "display_project_description": "",
        "candidate_project_name": candidate,
        "status": "normal",
        "is_in_progress": in_progress,
        "is_report_project": report_project_id != 1,
        "is_report_classified": report_project_id != 1,
        "is_report_uncategorized": report_project_id == 1,
        "report_attribution_kind": "official" if report_project_id != 1 else "none",
        "is_official_project": display_project_id > 0,
    }


def test_summary_groups_same_identity_within_accounted_project(monkeypatch):
    rows = [
        _row(1, identity="file:a", seconds=60, report_project_id=10, report_project_name="ProjectA", title="A"),
        _row(2, identity="file:a", seconds=120, report_project_id=10, report_project_name="ProjectA", title="A"),
        _row(3, identity="file:b", seconds=90, report_project_id=10, report_project_name="ProjectA", title="A"),
        _row(4, identity="file:a", seconds=300, report_project_id=20, report_project_name="ProjectB", title="A"),
    ]
    monkeypatch.setattr(timeline_service, "get_report_activity_rows", lambda *args, **kwargs: rows)

    summary = project_activity_summary_service.get_project_activity_summary("2026-07-09", 10)

    assert [item["activity_identity_key"] for item in summary] == ["file:a", "file:b"]
    assert summary[0]["duration_seconds"] == 180
    assert summary[0]["activity_ids"] == [1, 2]
    assert summary[1]["duration_seconds"] == 90


def test_summary_sorting_is_duration_desc(monkeypatch):
    rows = [
        _row(1, identity="small", seconds=10, report_project_id=10, report_project_name="ProjectA"),
        _row(2, identity="large", seconds=30, report_project_id=10, report_project_name="ProjectA"),
        _row(3, identity="middle", seconds=20, report_project_id=10, report_project_name="ProjectA"),
    ]
    monkeypatch.setattr(timeline_service, "get_report_activity_rows", lambda *args, **kwargs: rows)

    summary = project_activity_summary_service.get_project_activity_summary("2026-07-09", 10)

    assert [item["activity_identity_key"] for item in summary] == ["large", "middle", "small"]


def test_display_project_column_uses_official_policy_not_accounted_project(monkeypatch):
    rows = [
        _row(
            1,
            identity="short",
            seconds=45,
            report_project_id=10,
            report_project_name="ProjectA",
            display_project_id=20,
            display_project_name="ProjectB",
            title="Short absorbed activity",
        ),
        _row(
            2,
            identity="candidate",
            seconds=30,
            report_project_id=10,
            report_project_name="ProjectA",
            display_project_id=0,
            display_project_name=UNCATEGORIZED_PROJECT,
            candidate="SuggestedProject",
            title="Candidate activity",
        ),
    ]
    monkeypatch.setattr(timeline_service, "get_report_activity_rows", lambda *args, **kwargs: rows)

    summary = project_activity_summary_service.get_project_activity_summary("2026-07-09", 10)

    by_name = {item["activity_name"]: item for item in summary}
    assert by_name["Short absorbed activity"]["accounted_project_name"] == "ProjectA"
    assert by_name["Short absorbed activity"]["display_project_name"] == "ProjectB"
    assert by_name["Candidate activity"]["display_project_name"] == UNCATEGORIZED_PROJECT


def test_uncategorized_project_has_summary(monkeypatch):
    rows = [
        _row(1, identity="uncat", seconds=60, report_project_id=1, report_project_name=UNCATEGORIZED_PROJECT),
        _row(2, identity="other", seconds=60, report_project_id=10, report_project_name="ProjectA"),
    ]
    monkeypatch.setattr(timeline_service, "get_report_activity_rows", lambda *args, **kwargs: rows)

    summary = project_activity_summary_service.get_project_activity_summary("2026-07-09", 1)

    assert len(summary) == 1
    assert summary[0]["accounted_project_name"] == UNCATEGORIZED_PROJECT


def test_view_model_applies_today_live_span_once(monkeypatch):
    rows = [
        _row(
            7,
            identity="live",
            seconds=20,
            report_project_id=10,
            report_project_name="ProjectA",
            in_progress=True,
        )
    ]
    monkeypatch.setattr(project_activity_summary_service, "get_project_activity_summary", lambda *args, **kwargs: [
        {
            "row_kind": "project_activity_summary",
            "summary_id": "live",
            "activity_identity_key": "live",
            "activity_name": "Live",
            "duration_seconds": 20,
            "duration": "00:00:20",
            "accounted_project_id": 10,
            "accounted_project_name": "ProjectA",
            "project_id": 10,
            "project_name": "ProjectA",
            "project_description": "",
            "display_project_id": 10,
            "display_project_name": "ProjectA",
            "display_project_description": "",
            "activity_ids": [7],
            "open_activity_id": 7,
            "closed_duration_seconds": 0,
            "is_in_progress": True,
            "live_delta_eligible": False,
            "duration_semantic": "static_closed",
            "display_span_id": "",
            "stable_live_key_hash": "",
            "display_base_seconds": 20,
        }
    ])
    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: "2026-07-09")

    def fake_model(report_date=None, today=None, snapshot=None):
        return {
            "ok": True,
            "date": report_date,
            "sample_id": "sample",
            "current_activity": {},
            "live_clock": {
                "display_span_id": "span",
                "stable_live_key_hash": "hash",
                "is_live": True,
                "project_duration_live": True,
                "is_project_duration_live": True,
                "current_live_seconds_at_sample": 40,
                "current_elapsed_at_sample": 40,
                "aggregate_display_base_seconds": 5,
                "display_base_seconds": 5,
                "aggregate_duration_seconds_at_sample": 45,
            },
            "display_spans": [
                {
                    "display_span_id": "span",
                    "anchor_activity_id": 7,
                    "activity_id": 7,
                    "live_state": "persisted_open",
                    "is_visible_in_details": True,
                    "live_clock": {
                        "display_span_id": "span",
                        "stable_live_key_hash": "hash",
                        "is_live": True,
                        "project_duration_live": True,
                        "is_project_duration_live": True,
                        "current_live_seconds_at_sample": 40,
                        "current_elapsed_at_sample": 40,
                        "aggregate_display_base_seconds": 5,
                        "display_base_seconds": 5,
                        "aggregate_duration_seconds_at_sample": 45,
                    },
                }
            ],
        }

    monkeypatch.setattr(view_model_service, "build_activity_display_model", fake_model)

    result = view_model_service.get_project_activity_summary_view_model(10, "2026-07-09")

    row = result["summary_rows"][0]
    assert row["duration_seconds"] == 45
    assert row["duration_semantic"] == "aggregate_live"
    assert row["live_delta_eligible"] is True


def test_historical_view_model_not_polluted_by_today_live_runtime(monkeypatch):
    monkeypatch.setattr(project_activity_summary_service, "get_project_activity_summary", lambda *args, **kwargs: [
        {
            "row_kind": "project_activity_summary",
            "summary_id": "history",
            "activity_identity_key": "history",
            "activity_name": "History",
            "duration_seconds": 20,
            "duration": "00:00:20",
            "accounted_project_id": 10,
            "accounted_project_name": "ProjectA",
            "project_id": 10,
            "project_name": "ProjectA",
            "project_description": "",
            "display_project_id": 10,
            "display_project_name": "ProjectA",
            "display_project_description": "",
            "activity_ids": [7],
            "open_activity_id": 7,
            "closed_duration_seconds": 0,
            "is_in_progress": True,
            "live_delta_eligible": False,
            "duration_semantic": "static_closed",
            "display_span_id": "",
            "stable_live_key_hash": "",
            "display_base_seconds": 20,
        }
    ])
    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: "2026-07-09")

    def fake_model(report_date=None, today=None, snapshot=None):
        if report_date == "2026-07-08":
            return {"ok": True, "date": report_date, "live_clock": {}, "current_activity": {}, "display_spans": []}
        return {
            "ok": True,
            "date": report_date,
            "sample_id": "today",
            "current_activity": {},
            "live_clock": {"display_span_id": "today-span", "stable_live_key_hash": "today"},
            "display_spans": [
                {
                    "display_span_id": "today-span",
                    "anchor_activity_id": 7,
                    "activity_id": 7,
                    "is_visible_in_details": True,
                    "live_clock": {
                        "display_span_id": "today-span",
                        "stable_live_key_hash": "today",
                        "current_live_seconds_at_sample": 999,
                        "project_duration_live": True,
                    },
                }
            ],
        }

    monkeypatch.setattr(view_model_service, "build_activity_display_model", fake_model)

    result = view_model_service.get_project_activity_summary_view_model(10, "2026-07-08")

    row = result["summary_rows"][0]
    assert row["duration_seconds"] == 20
    assert row["live_delta_eligible"] is False
    assert row["display_span_id"] == ""
