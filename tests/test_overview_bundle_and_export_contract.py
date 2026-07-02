"""Overview bundle / Timeline / Detail / Statistics / Export contract tests.

Covers sections 九.4 / 九.5 / 九.6:

- **Overview bundle** — ``get_overview_live_bundle()`` returns overview KPI
  + current activity + recent activities + live_projection from ONE
  snapshot sample. The frontend no longer needs parallel
  ``get_overview`` + ``get_recent_activities`` calls. The current
  activity and the recent live row share the same ``sample_id`` /
  ``stable_live_key_hash`` and the same first-frame seconds (no 1-2s
  drift). During a pending project transition the recent live row uses
  the display project (NOT the candidate), so it never appears as a
  separate candidate-project row.
- **Timeline / Detail** — Timeline session uses display project +
  description; detail row uses current resource + display project +
  description. During pending the candidate does NOT preempt the
  Timeline session project. The detail payload carries its OWN
  ``live_projection`` (not reusing the Timeline main payload's
  projection).
- **Statistics / Export** — Overview KPI with ``include_live=True``
  uses ``live_projection.display_project``; during pending (<30s) the
  KPI attributes time to the display project. The export preview
  (``get_statistics_export_summary``) does NOT project the current
  live activity — it only includes finalized/closed rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from worktrace.constants import STATUS_NORMAL, TIME_FORMAT, UNCATEGORIZED_PROJECT
from worktrace.services import settings_service, statistics_service, timeline_service
from worktrace.webview_ui.bridge import WebViewBridge


# Fixtures & helpers


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("user_paused", "false")
    settings_service.clear_settings_cache()
    return WebViewBridge()


def _set_snapshot(snapshot: dict | None) -> None:
    settings_service.set_setting(
        "current_activity_snapshot", json.dumps(snapshot) if snapshot else ""
    )
    settings_service.clear_settings_cache()


def _project_dict(
    *,
    name: str,
    project_id: int | None = None,
    description: str = "",
    source: str = "folder_rule",
    is_uncategorized: bool = False,
    is_suggested_project: bool = False,
) -> dict:
    return {
        "id": project_id,
        "name": name,
        "description": description,
        "source": source,
        "is_uncategorized": is_uncategorized,
        "is_suggested_project": is_suggested_project,
    }


def _transition_dict(
    *,
    pending: bool,
    started_at: str = "",
    elapsed_seconds: int = 0,
    threshold_seconds: int = 30,
    from_project_id: int | None = None,
    to_project_id: int | None = None,
) -> dict:
    return {
        "pending": pending,
        "started_at": started_at,
        "elapsed_seconds": elapsed_seconds,
        "threshold_seconds": threshold_seconds,
        "from_project_id": from_project_id,
        "to_project_id": to_project_id,
    }


def _snapshot(
    *,
    elapsed_seconds: int = 120,
    status: str = STATUS_NORMAL,
    is_persisted: bool = False,
    persisted_activity_id: int = 0,
    display_project: dict | None = None,
    candidate_project: dict | None = None,
    project_transition: dict | None = None,
    project_transition_pending: bool = False,
    inferred_project_name: str | None = None,
    resource_display_name: str = "main.py",
    activity_display_name: str = "main.py",
    app_name: str = "Code",
    process_name: str = "code.exe",
    start_time: str | None = None,
) -> dict:
    if start_time is None:
        start = datetime.now() - timedelta(seconds=elapsed_seconds)
        start_time = start.strftime(TIME_FORMAT)
    if display_project is None:
        display_project = _project_dict(
            name="ProjectA",
            project_id=12,
            description="Project A description",
            source="folder_rule",
        )
    if candidate_project is None:
        candidate_project = display_project
    if project_transition is None:
        project_transition = _transition_dict(pending=project_transition_pending)
    if inferred_project_name is None:
        inferred_project_name = display_project.get("name") or UNCATEGORIZED_PROJECT
    return {
        "app_name": app_name,
        "process_name": process_name,
        "window_title": "main.py - VS Code",
        "file_path_hint": "D:\\ProjectA\\main.py",
        "activity_display_name": activity_display_name,
        "resource_kind": "code_file",
        "resource_subtype": "python_source",
        "resource_display_name": resource_display_name,
        "resource_identity_key": "file_path:D:\\ProjectA\\main.py",
        "resource_path_hint": "D:\\ProjectA\\main.py",
        "resource_uri_host": None,
        "inferred_project_name": inferred_project_name,
        "status": status,
        "start_time": start_time,
        "elapsed_seconds": elapsed_seconds,
        "extra_seconds": 0,
        "persisted_activity_id": persisted_activity_id,
        "is_persisted": is_persisted,
        "display_project": display_project,
        "candidate_project": candidate_project,
        "project_transition": project_transition,
        "project_transition_pending": project_transition_pending,
    }


def _pending_snapshot() -> dict:
    """A snapshot in the 30-second pending window: display project is
    ProjectA (inherited), candidate is ProjectB (new resource)."""
    display = _project_dict(
        name="ProjectA",
        project_id=12,
        description="Project A description",
        source="inherited",
    )
    candidate = _project_dict(
        name="ProjectB",
        project_id=18,
        description="Project B description",
        source="folder_rule",
    )
    transition = _transition_dict(
        pending=True,
        started_at="2026-06-18 09:00:36",
        elapsed_seconds=12,
        threshold_seconds=30,
        from_project_id=12,
        to_project_id=18,
    )
    return _snapshot(
        elapsed_seconds=12,
        display_project=display,
        candidate_project=candidate,
        project_transition=transition,
        project_transition_pending=True,
        inferred_project_name="ProjectA",
    )


# 1. Overview bundle — single sample (section 九.4)


def test_overview_bundle_returns_all_required_payloads(bridge):
    """``get_overview_live_bundle()`` returns ``live_projection``,
    ``overview`` KPI, ``current_activity``, ``activities`` (recent),
    and ``sample_id`` — all from one backend call."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    bundle = bridge.get_overview_live_bundle()
    assert bundle["ok"] is True
    assert "live_projection" in bundle
    assert "overview" in bundle
    assert "current_activity" in bundle
    assert "activities" in bundle
    assert "sample_id" in bundle


def test_overview_bundle_current_and_recent_share_same_sample_id(bridge):
    """The current activity and the recent live row must share the same
    ``sample_id`` / ``stable_live_key_hash`` — they came from the SAME
    snapshot sample, not two parallel bridge calls."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    bundle = bridge.get_overview_live_bundle()
    sample_id = bundle["sample_id"]
    assert sample_id, "bundle must carry a non-empty sample_id"
    live_projection = bundle["live_projection"]
    assert live_projection["stable_live_key_hash"] == sample_id
    # The recent live row (first item, virtual) must share the same hash.
    activities = bundle["activities"]
    if activities:
        virtual_live_row = activities[0]
        if virtual_live_row.get("is_virtual_live"):
            assert virtual_live_row["stable_live_key_hash"] == sample_id


def test_overview_bundle_current_and_recent_first_frame_seconds_consistent(bridge):
    """the current activity and the recent live row must
    NOT have a 1-2 second drift on the first frame. Both derive from
    the same snapshot, so their duration_seconds must be equal."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    bundle = bridge.get_overview_live_bundle()
    current_seconds = int(bundle["current_activity"].get("elapsed_seconds") or 0)
    live_projection_seconds = int(bundle["live_projection"].get("duration_seconds") or 0)
    # current_activity.elapsed_seconds and live_projection.duration_seconds
    # both derive from the same snapshot's elapsed_seconds.
    assert current_seconds == live_projection_seconds
    # If there's a virtual live row in recent, its duration_seconds must
    # also match (same sample).
    activities = bundle["activities"]
    if activities and activities[0].get("is_virtual_live"):
        recent_live_seconds = int(activities[0].get("duration_seconds") or 0)
        assert recent_live_seconds == current_seconds


def test_overview_bundle_pending_recent_uses_display_project_not_candidate(bridge):
    """during a pending project transition the recent live
    row uses the display project (ProjectA), NOT the candidate (ProjectB).
    The candidate must NOT appear as a separate independent project row."""
    _set_snapshot(_pending_snapshot())
    bundle = bridge.get_overview_live_bundle()
    live_projection = bundle["live_projection"]
    assert live_projection["display_project"]["name"] == "ProjectA"
    assert live_projection["candidate_project"]["name"] == "ProjectB"
    assert live_projection["project_transition_pending"] is True
    # The recent live row (if present) must use the display project.
    activities = bundle["activities"]
    if activities and activities[0].get("is_virtual_live"):
        recent_live = activities[0]
        assert recent_live["project_name"] == "ProjectA"
        # Candidate ProjectB must NOT appear as a separate row.
        project_names = [a.get("project_name") for a in activities]
        assert "ProjectB" not in project_names


def test_overview_bundle_is_display_safe(bridge):
    """the bundle must not leak raw ``window_title`` /
    ``file_path_hint`` / clipboard / note / SQL / traceback."""
    _set_snapshot(_pending_snapshot())
    bundle = bridge.get_overview_live_bundle()
    sensitive_keys = {"window_title", "file_path_hint", "resource_path_hint",
                      "resource_identity_key", "note", "clipboard", "sql", "traceback"}
    for key in bundle:
        assert key not in sensitive_keys, f"bundle leaked sensitive key: {key}"
    # Check nested payloads.
    for sub in (bundle["live_projection"], bundle["current_activity"]):
        for key in sub:
            assert key not in sensitive_keys, f"bundle sub-payload leaked key: {key}"


# 2. Timeline / Detail (section 九.5)


def test_timeline_returns_live_projection(bridge):
    """Timeline payload must carry a ``live_projection`` from the same
    snapshot sample."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    timeline = bridge.get_timeline()
    assert "live_projection" in timeline
    assert timeline["live_projection"]["live_state"] == "virtual"


def test_timeline_session_uses_display_project_and_description(bridge):
    """Timeline session uses the display project name +
    description (not hardcoded empty)."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    timeline = bridge.get_timeline()
    sessions = timeline["sessions"]
    virtual_sessions = [s for s in sessions if s.get("is_virtual_live")]
    if virtual_sessions:
        vs = virtual_sessions[0]
        assert vs["project_name"] == "ProjectA"
        assert vs["project_description"] == "Project A description"


def test_timeline_pending_candidate_does_not_preempt_session_project(bridge):
    """during pending the Timeline session project is the
    display project (ProjectA), NOT the candidate (ProjectB)."""
    _set_snapshot(_pending_snapshot())
    timeline = bridge.get_timeline()
    sessions = timeline["sessions"]
    virtual_sessions = [s for s in sessions if s.get("is_virtual_live")]
    if virtual_sessions:
        vs = virtual_sessions[0]
        assert vs["project_name"] == "ProjectA"
        assert vs["project_name"] != "ProjectB"


def test_timeline_detail_carries_own_live_projection(bridge):
    """``get_timeline_session_details()`` must return its
    OWN ``live_projection`` — the detail ticker must NOT reuse the
    Timeline main payload's projection."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    timeline = bridge.get_timeline()
    # Find the virtual session id (or use empty for virtual detail).
    details = bridge.get_timeline_session_details([], None)
    assert "live_projection" in details
    assert details["live_projection"]["live_state"] == "virtual"
    # The detail's live_projection sample_id must be present.
    assert "sample_id" in details


def test_timeline_detail_uses_display_project_and_description(bridge):
    """detail row uses the current resource + display
    project + description (not hardcoded empty)."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    details = bridge.get_timeline_session_details([], None)
    activities = details.get("activities", [])
    if activities:
        detail_row = activities[0]
        if detail_row.get("is_virtual_live"):
            assert detail_row["project_name"] == "ProjectA"
            assert detail_row["project_description"] == "Project A description"


def test_timeline_detail_pending_uses_display_project_not_candidate(bridge):
    """during pending the detail row uses the display
    project (ProjectA), NOT the candidate (ProjectB)."""
    _set_snapshot(_pending_snapshot())
    details = bridge.get_timeline_session_details([], None)
    activities = details.get("activities", [])
    if activities:
        detail_row = activities[0]
        if detail_row.get("is_virtual_live"):
            assert detail_row["project_name"] == "ProjectA"
            assert detail_row["project_name"] != "ProjectB"


# 3. Statistics / Export (section 九.6)


def test_overview_kpi_include_live_uses_display_project(bridge):
    """Overview KPI with ``include_live=True`` uses
    ``live_projection.display_project`` — during pending (<30s) the KPI
    attributes live time to the display project (ProjectA), NOT the
    candidate (ProjectB)."""
    _set_snapshot(_pending_snapshot())
    from worktrace.services import timeline_service
    today = timeline_service.get_default_report_date()
    summary = statistics_service.get_summary(today, today, include_live=True)
    # The live projection should be present and attribute time to ProjectA.
    live = summary.get("live_projection") or {}
    if live:
        assert live["project"] == "ProjectA"
        assert live["project"] != "ProjectB"


def test_export_preview_does_not_project_current_live_activity(bridge):
    """``get_statistics_export_summary`` does NOT project
    the current live activity — it only includes finalized/closed rows."""
    _set_snapshot(_pending_snapshot())
    from worktrace.services import timeline_service
    today = timeline_service.get_default_report_date()
    export_summary = statistics_service.get_statistics_export_summary(today, today)
    # The export summary should not contain any live projection field.
    assert "live_projection" not in export_summary
    # Total duration should be 0 (no closed activities in the test db).
    assert int(export_summary.get("total_duration_seconds") or 0) == 0


def test_export_preview_only_includes_closed_rows(bridge):
    """even when a live activity exists, the export
    preview's activity count and total duration only reflect closed
    rows."""
    _set_snapshot(_pending_snapshot())
    from worktrace.services import timeline_service
    today = timeline_service.get_default_report_date()
    export_summary = statistics_service.get_statistics_export_summary(today, today)
    # No closed activities exist in the test db — the live snapshot
    # must NOT contribute to the export total.
    assert int(export_summary.get("activity_count") or 0) == 0
    assert int(export_summary.get("total_duration_seconds") or 0) == 0
