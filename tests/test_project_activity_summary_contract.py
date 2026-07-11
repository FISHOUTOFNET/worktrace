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
    report_project_id: int = 10,
    report_project_name: str = "ProjectA",
    display_project_id: int = 10,
    display_project_name: str = "ProjectA",
    display_project_description: str = "",
    title: str = "Same title",
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
        "report_project_description": "Report description",
        "project_id": report_project_id,
        "project_name": report_project_name,
        "project_description": "Report description",
        "display_project_id": display_project_id,
        "display_project_name": display_project_name,
        "display_project_description": display_project_description,
        "status": "normal",
        "is_in_progress": in_progress,
        "is_report_project": report_project_id != 1,
        "is_report_classified": report_project_id != 1,
        "is_report_uncategorized": report_project_id == 1,
        "report_attribution_kind": "official" if report_project_id != 1 else "none",
        "is_official_project": display_project_id > 0,
    }


def _closed_model(report_date: str = "2026-07-09") -> dict:
    return {
        "ok": True,
        "date": report_date,
        "sample_id": "sample",
        "current_activity": {},
        "live_clock": {},
        "display_spans": [],
    }


def test_session_activity_summary_is_scoped_by_activity_ids(monkeypatch):
    first_session_rows = [
        _row(1, identity="file:first", seconds=60, title="First session"),
    ]
    second_session_rows = [
        _row(2, identity="file:second", seconds=300, title="Second session"),
    ]

    def fake_details(activity_ids, report_date=None, ensure_context=True):
        assert report_date == "2026-07-09"
        if activity_ids == [1]:
            return first_session_rows
        if activity_ids == [2]:
            return second_session_rows
        return first_session_rows + second_session_rows

    monkeypatch.setattr(timeline_service, "get_session_activity_details", fake_details)

    summary = project_activity_summary_service.get_session_activity_summary([1], "2026-07-09")

    assert [item["activity_identity_key"] for item in summary] == ["file:first"]
    assert summary[0]["activity_ids"] == [1]
    assert summary[0]["duration_seconds"] == 60


def test_same_project_different_sessions_have_different_summaries(monkeypatch):
    def fake_details(activity_ids, report_date=None, ensure_context=True):
        if activity_ids == [11]:
            return [_row(11, identity="file:morning", seconds=120, title="Morning")]
        if activity_ids == [22]:
            return [_row(22, identity="file:afternoon", seconds=480, title="Afternoon")]
        return []

    monkeypatch.setattr(timeline_service, "get_session_activity_details", fake_details)

    first = project_activity_summary_service.get_session_activity_summary([11], "2026-07-09")
    second = project_activity_summary_service.get_session_activity_summary([22], "2026-07-09")

    assert first != second
    assert first[0]["activity_name"] == "Morning"
    assert second[0]["activity_name"] == "Afternoon"
    assert first[0]["duration_seconds"] == 120
    assert second[0]["duration_seconds"] == 480


def test_session_activity_summary_preserves_report_projection(monkeypatch):
    rows = [
        _row(
            7,
            identity="short-context",
            seconds=45,
            report_project_id=10,
            report_project_name="ReportProject",
            display_project_id=20,
            display_project_name="OfficialProject",
            display_project_description="Official description",
            title="Short absorbed activity",
        )
    ]
    monkeypatch.setattr(timeline_service, "get_session_activity_details", lambda *args, **kwargs: rows)

    summary = project_activity_summary_service.get_session_activity_summary([7], "2026-07-09")

    assert summary[0]["accounted_project_name"] == "ReportProject"
    assert summary[0]["project_name"] == "ReportProject"
    assert summary[0]["display_project_name"] == "OfficialProject"
    assert summary[0]["display_project_description"] == "Official description"
    assert summary[0]["is_report_project"] is True
    assert summary[0]["is_official_project"] is True


def test_session_activity_summary_live_overlay_requires_selected_activity_match(monkeypatch):
    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: "2026-07-09")
    monkeypatch.setattr(
        project_activity_summary_service,
        "get_projection_session_activity_summary",
        lambda *args, **kwargs: [
            {
                "row_kind": "project_activity_summary",
                "summary_id": "selected",
                "activity_identity_key": "selected",
                "activity_name": "Selected",
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
                "open_activity_id": 0,
                "closed_duration_seconds": 20,
                "is_in_progress": False,
                "live_delta_eligible": False,
                "duration_semantic": "static_closed",
                "display_span_id": "",
                "stable_live_key_hash": "",
                "display_base_seconds": 20,
            }
        ],
    )
    monkeypatch.setattr(timeline_service, "get_session_activity_details", lambda *args, **kwargs: [])

    def fake_model(report_date=None, today=None, snapshot=None):
        model = _closed_model(report_date or "2026-07-09")
        model["current_activity"] = {"app_name": "LiveApp", "resource_name": "Other live"}
        model["live_clock"] = {
            "display_span_id": "span",
            "stable_live_key_hash": "hash",
            "is_live": True,
            "project_duration_live": True,
            "is_project_duration_live": True,
            "current_live_seconds_at_sample": 40,
            "aggregate_display_base_seconds": 5,
            "display_base_seconds": 5,
            "aggregate_duration_seconds_at_sample": 45,
        }
        model["display_spans"] = [
            {
                "display_span_id": "span",
                "anchor_activity_id": 999,
                "activity_id": 999,
                "is_visible_in_details": True,
                "live_state": "persisted_open",
                "live_clock": model["live_clock"],
            }
        ]
        return model

    monkeypatch.setattr(view_model_service, "build_activity_display_model", fake_model)

    result = view_model_service.get_session_activity_summary_view_model(
        report_date="2026-07-09", projection_instance_key="base:selected"
    )

    row = result["summary_rows"][0]
    assert row["duration_seconds"] == 20
    assert row["live_delta_eligible"] is False
    assert row["display_span_id"] == ""
    assert len(result["summary_rows"]) == 1


def test_uncategorized_session_activity_has_summary(monkeypatch):
    rows = [
        _row(
            1,
            identity="uncat",
            seconds=60,
            report_project_id=1,
            report_project_name=UNCATEGORIZED_PROJECT,
            display_project_id=0,
            display_project_name=UNCATEGORIZED_PROJECT,
        )
    ]
    monkeypatch.setattr(timeline_service, "get_session_activity_details", lambda *args, **kwargs: rows)

    summary = project_activity_summary_service.get_session_activity_summary([1], "2026-07-09")

    assert len(summary) == 1
    assert summary[0]["accounted_project_name"] == UNCATEGORIZED_PROJECT
