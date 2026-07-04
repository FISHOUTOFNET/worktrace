"""Overview bundle / Timeline / Detail / Statistics / Export contract tests.

Covers sections 九.4 / 九.5 / 九.6:

- **Overview ViewModel** — ``get_overview()`` returns overview KPI
  + current activity + recent activities + ``live_clock`` from ONE
  snapshot sample. The current activity and the recent live row share
  the same ``sample_id`` / ``stable_live_key_hash`` and the same
  first-frame seconds (no 1-2s drift). During a pending project
  transition the recent live row uses the display project (NOT the
  candidate), so it never appears as a separate candidate-project row.
- **Timeline / Detail** — Timeline session uses display project +
  description; detail row uses current resource + display project +
  description. During pending the candidate does NOT preempt the
  Timeline session project. The detail payload carries its OWN
  ``live_clock`` (not reusing the Timeline main payload's clock).
- **Statistics / Export** — Statistics is DB-only (no ``include_live``
  parameter). The export preview (``get_statistics_export_summary``)
  does NOT project the current live activity — it only includes
  finalized/closed rows.
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
    extra_seconds: int = 0,
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
        "extra_seconds": extra_seconds,
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


# 1. Overview ViewModel — single sample (section 九.4)


def test_overview_view_model_returns_all_required_payloads(bridge):
    """``get_overview()`` returns ``live_clock``,
    ``overview`` KPI, ``current_activity``, ``activities`` (recent),
    and ``sample_id`` — all from one backend call."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    bundle = bridge.get_overview()
    assert bundle["ok"] is True
    assert "live_clock" in bundle
    assert "overview" in bundle
    assert "current_activity" in bundle
    assert "activities" in bundle
    assert "sample_id" in bundle


def test_overview_view_model_current_and_recent_share_same_sample_id(bridge):
    """The current activity and the recent live row must share the same
    ``sample_id`` / ``stable_live_key_hash`` — they came from the SAME
    snapshot sample, not two parallel bridge calls."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    bundle = bridge.get_overview()
    sample_id = bundle["sample_id"]
    assert sample_id, "bundle must carry a non-empty sample_id"
    live_clock = bundle["live_clock"]
    assert live_clock["stable_live_key_hash"] == sample_id
    # The recent live row (first item, virtual) must share the same hash.
    activities = bundle["activities"]
    if activities:
        virtual_live_row = activities[0]
        if virtual_live_row.get("is_virtual_live"):
            assert virtual_live_row["stable_live_key_hash"] == sample_id


def test_overview_view_model_current_and_recent_first_frame_seconds_consistent(bridge):
    """the current activity and the recent live row must
    NOT have a 1-2 second drift on the first frame. Both derive from
    the same snapshot, so their duration_seconds must be equal."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    bundle = bridge.get_overview()
    current_seconds = int(bundle["current_activity"].get("elapsed_seconds") or 0)
    live_clock_seconds = int(bundle["live_clock"].get("duration_seconds_at_sample") or 0)
    # current_activity.elapsed_seconds and live_clock.duration_seconds_at_sample
    # both derive from the same snapshot's elapsed_seconds.
    assert current_seconds == live_clock_seconds
    # If there's a virtual live row in recent, its duration_seconds must
    # also match (same sample).
    activities = bundle["activities"]
    if activities and activities[0].get("is_virtual_live"):
        recent_live_seconds = int(activities[0].get("duration_seconds") or 0)
        assert recent_live_seconds == current_seconds


def test_overview_view_model_pending_recent_uses_display_project_not_candidate(bridge):
    """during a pending project transition the recent live
    row uses the display project (ProjectA), NOT the candidate (ProjectB).
    The candidate must NOT appear as a separate independent project row."""
    _set_snapshot(_pending_snapshot())
    bundle = bridge.get_overview()
    current_activity = bundle["current_activity"]
    assert current_activity["display_project"]["name"] == "ProjectA"
    assert current_activity["candidate_project"]["name"] == "ProjectB"
    assert current_activity["project_transition_pending"] is True
    # The recent live row (if present) must use the display project.
    activities = bundle["activities"]
    if activities and activities[0].get("is_virtual_live"):
        recent_live = activities[0]
        assert recent_live["project_name"] == "ProjectA"
        # Candidate ProjectB must NOT appear as a separate row.
        project_names = [a.get("project_name") for a in activities]
        assert "ProjectB" not in project_names


def test_overview_view_model_is_display_safe(bridge):
    """the bundle must not leak raw ``window_title`` /
    ``file_path_hint`` / clipboard / note / SQL / traceback."""
    _set_snapshot(_pending_snapshot())
    bundle = bridge.get_overview()
    sensitive_keys = {"window_title", "file_path_hint", "resource_path_hint",
                      "resource_identity_key", "note", "clipboard", "sql", "traceback"}
    for key in bundle:
        assert key not in sensitive_keys, f"bundle leaked sensitive key: {key}"
    # Check nested payloads.
    for sub in (bundle["live_clock"], bundle["current_activity"]):
        for key in sub:
            assert key not in sensitive_keys, f"bundle sub-payload leaked key: {key}"


# 2. Timeline / Detail (section 九.5)


def test_timeline_returns_live_clock(bridge):
    """Timeline payload must carry a ``live_clock`` from the same
    snapshot sample. Under the unified Activity Display Model the legacy
    ``"virtual"`` state is split into ``"virtual_pending"`` (no absorb
    anchor) / ``"absorbed_pending"`` (absorb anchor exists); a fresh
    unpersisted normal snapshot with no prior confirmed activity yields
    ``"virtual_pending"``."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    timeline = bridge.get_timeline()
    assert "live_clock" in timeline
    assert timeline["live_clock"]["live_state"] == "virtual_pending"


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


def test_timeline_detail_carries_own_live_clock(bridge):
    """``get_timeline_session_details()`` must return its
    OWN ``live_clock`` — the detail ticker must NOT reuse the
    Timeline main payload's clock. Under the unified Activity
    Display Model the legacy ``"virtual"`` state is split into
    ``"virtual_pending"`` / ``"absorbed_pending"``; a fresh unpersisted
    normal snapshot with no prior confirmed activity yields
    ``"virtual_pending"``."""
    _set_snapshot(_snapshot(elapsed_seconds=120))
    timeline = bridge.get_timeline()
    # Find the virtual session id (or use empty for virtual detail).
    details = bridge.get_timeline_session_details([], None)
    assert "live_clock" in details
    assert details["live_clock"]["live_state"] == "virtual_pending"
    # The detail's live_clock sample_id must be present.
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


# 4. Overview KPI classified / uncategorized split (section 一)


def test_overview_kpi_classified_uncategorized_split_explicit_fields(bridge):
    """Section 一: ``_session_to_overview_row`` MUST propagate
    ``project_id`` / ``is_uncategorized`` / ``is_classified`` from the
    source session so the Overview KPI split is based on a positive
    field check, not on a missing field's falsy default.

    With one classified session (60s) and one uncategorized session
    (45s), the KPI must satisfy:

    * ``today_total_seconds == classified_seconds + uncategorized_seconds``
    * ``classified_seconds`` includes ONLY the classified session
    * ``uncategorized_seconds`` includes ONLY the uncategorized session
    * the corresponding recent rows carry the correct
      ``is_uncategorized`` / ``is_classified`` flags
    """
    from worktrace.services import activity_service, project_service

    today = datetime.now().strftime("%Y-%m-%d")
    # 1. Create a classified project + classified closed activity (60s).
    pid = project_service.create_project("ClassifiedProject")
    classified_aid = activity_service.create_activity(
        "ClassifiedApp",
        "ClassifiedApp.exe",
        "ClassifiedWindow",
        start_time=f"{today} 09:00:00",
        project_id=pid,
    )
    activity_service.close_activity(classified_aid, f"{today} 09:01:00", 60)

    # 2. Uncategorized closed activity (45s). Lock via MANUAL assignment so
    #    context_service carry logic does NOT auto-classify it into the
    #    preceding ClassifiedProject session.
    uncategorized_id = project_service.get_or_create_uncategorized_project()
    uncategorized_aid = activity_service.create_activity(
        "UncategorizedApp",
        "UncategorizedApp.exe",
        "UncategorizedWindow",
        start_time=f"{today} 09:02:00",
    )
    activity_service.close_activity(uncategorized_aid, f"{today} 09:02:45", 45)
    activity_service.update_activity_project(
        uncategorized_aid, uncategorized_id, manual=True
    )

    # No live snapshot — KPI comes purely from DB rows.
    _set_snapshot(None)
    bundle = bridge.get_overview()
    assert bundle["ok"] is True

    today_total = int(bundle["today_total_seconds"])
    classified = int(bundle["classified_seconds"])
    uncategorized = int(bundle["uncategorized_seconds"])

    # KPI identity: total == classified + uncategorized.
    assert today_total == classified + uncategorized, (
        f"today_total_seconds ({today_total}) must equal classified "
        f"({classified}) + uncategorized ({uncategorized})"
    )
    # Explicit split: classified == 60, uncategorized == 45.
    assert classified == 60, (
        f"classified_seconds must include ONLY the classified session (60s), "
        f"got {classified}"
    )
    assert uncategorized == 45, (
        f"uncategorized_seconds must include ONLY the uncategorized session "
        f"(45s), got {uncategorized}"
    )

    # The recent rows must carry the correct classification flags.
    activities = bundle["activities"]
    classified_row = next(
        (a for a in activities if int(a.get("activity_id") or 0) == classified_aid),
        None,
    )
    uncategorized_row = next(
        (a for a in activities if int(a.get("activity_id") or 0) == uncategorized_aid),
        None,
    )
    assert classified_row is not None, "classified session not found in activities"
    assert uncategorized_row is not None, "uncategorized session not found in activities"

    assert classified_row["is_classified"] is True
    assert classified_row["is_uncategorized"] is False
    assert int(classified_row["project_id"]) == pid

    assert uncategorized_row["is_uncategorized"] is True
    assert uncategorized_row["is_classified"] is False
    assert int(uncategorized_row["project_id"]) == uncategorized_id


def test_overview_kpi_persisted_open_uses_same_sample_as_recent_and_current(bridge):
    """Section 一: under a ``persisted_open`` overlay, the Overview KPI
    base, the Recent row's display duration, and the current-activity
    area's elapsed seconds MUST all derive from the SAME live sample.
    The frontend ticker only adds the live delta on top; the sample
    seconds MUST NOT be double-counted.

    With a persisted_open snapshot (elapsed=210, extra=30 → sample=240),
    the KPI ``classified_seconds`` base, the Recent row's
    ``live_base_seconds``, and ``current_activity.elapsed_seconds`` must
    all equal 240 and share the same ``stable_live_key_hash``.
    """
    from worktrace.services import activity_service, project_service

    pid = project_service.create_project("MyProject")
    aid, start_time = _create_real_open_activity_helper(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title="main.py - Visual Studio Code",
        file_path_hint="D:\\MyProject\\main.py",
        elapsed_seconds=210,
    )
    activity_service.update_activity_project(aid, pid)
    assert activity_service.get_activity(aid)["project_name"] == "MyProject"

    _set_snapshot(
        _snapshot(
            elapsed_seconds=210,
            extra_seconds=30,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
            display_project=_project_dict(
                name="MyProject",
                project_id=pid,
                description="MyProject description",
                source="folder_rule",
            ),
        )
    )

    bundle = bridge.get_overview()
    assert bundle["ok"] is True

    live_clock = bundle["live_clock"]
    sample_duration = int(live_clock["duration_seconds_at_sample"])
    sample_hash = live_clock["stable_live_key_hash"]
    assert sample_duration == 240, (
        f"persisted_open sample duration must be 240 (210 elapsed + 30 extra), "
        f"got {sample_duration}"
    )

    # KPI classified_seconds base must equal the sample duration (counted once).
    classified = int(bundle["classified_seconds"])
    assert classified == sample_duration, (
        f"Overview classified_seconds ({classified}) must equal the live "
        f"sample duration ({sample_duration}) — counted exactly once, not "
        f"double-counted"
    )
    assert int(bundle["uncategorized_seconds"]) == 0
    assert int(bundle["today_total_seconds"]) == sample_duration

    # kpi_live_base must match the sample so the frontend ticker only
    # adds the live delta.
    kpi_base = bundle["kpi_live_base"]
    assert int(kpi_base["classified_seconds"]) == sample_duration
    assert int(kpi_base["today_total_seconds"]) == sample_duration

    # The Recent row must carry the same sample duration and hash.
    recent_row = next(
        (a for a in bundle["activities"] if int(a.get("activity_id") or 0) == aid),
        None,
    )
    assert recent_row is not None, "persisted_open row not found in activities"
    assert int(recent_row["live_base_seconds"]) == sample_duration, (
        f"Recent row live_base_seconds ({recent_row['live_base_seconds']}) "
        f"must equal the sample duration ({sample_duration})"
    )
    assert recent_row["stable_live_key_hash"] == sample_hash

    # current_activity.elapsed_seconds must equal the sample duration.
    current = bundle["current_activity"]
    assert int(current["elapsed_seconds"]) == sample_duration, (
        f"current_activity.elapsed_seconds ({current['elapsed_seconds']}) "
        f"must equal the sample duration ({sample_duration})"
    )
    assert current["stable_live_key_hash"] == sample_hash


def _create_real_open_activity_helper(
    *,
    app_name: str = "AppA",
    process_name: str = "AppA.exe",
    window_title: str = "Window",
    file_path_hint: str | None = None,
    elapsed_seconds: int = 120,
) -> tuple[int, str]:
    """Create a real open (``end_time IS NULL``) activity row and return
    ``(activity_id, start_time)``."""
    from worktrace.services import activity_service

    start = datetime.now() - timedelta(seconds=elapsed_seconds)
    start_time = start.strftime(TIME_FORMAT)
    aid = activity_service.create_activity(
        app_name,
        process_name,
        window_title,
        file_path_hint=file_path_hint,
        start_time=start_time,
    )
    return aid, start_time


# Real-session live overlay regression: a closed-then-open session MUST
# be overlaid via ``activity_ids`` match (not ``activity_id`` equality) so
# Overview recent / KPI / Timeline aggregate share one live sample.


def test_overview_recent_session_with_closed_then_open_activity_gets_live_overlay(
    bridge,
):
    """Regression: a closed-then-open session MUST overlay via
    ``activity_ids`` match. ``_session_to_overview_row`` previously dropped
    ``activity_ids`` / ``first_activity_id``, so when the open activity was
    NOT the session's first activity, ``apply_live_span_to_row`` could not
    match the persisted_open anchor and the Overview recent row / KPI totals
    froze at DB-only duration while the current-activity area kept ticking.

    Scenario (real Timeline session order, no synthetic row): project ``P``,
    closed 60s + persisted_open DB duration 0 (no boundary → one session
    ``activity_ids == [closed_id, open_id]``), snapshot ``is_persisted=True``
    / ``persisted_activity_id=open_id`` / ``elapsed_seconds=100``.

    Asserts: recent row ``activity_ids == [closed_id, open_id]`` /
    ``first_activity_id == closed_id``; ``duration_seconds == 160`` /
    ``live_base_seconds == 160``; ``today_total_seconds == 160`` /
    ``classified_seconds == 160`` / ``uncategorized_seconds == 0``;
    ``current_activity.elapsed_seconds == 100`` (open OWN sample);
    Timeline same session 160 (Overview ↔ Timeline agree)."""
    from worktrace.services import activity_service, project_service

    pid = project_service.create_project("P")
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. Closed activity in P (60s).
    closed_start = datetime.now() - timedelta(seconds=200)
    closed_end = closed_start + timedelta(seconds=60)
    closed_id = activity_service.create_activity(
        "AppP",
        "AppP.exe",
        "ClosedWindow",
        start_time=closed_start.strftime(TIME_FORMAT),
        project_id=pid,
    )
    activity_service.close_activity(
        closed_id, closed_end.strftime(TIME_FORMAT), 60
    )

    # 2. Persisted open activity in P (DB duration 0). Start it right
    #    after the closed activity so they merge into one session
    #    (no boundary recorded).
    open_start = datetime.now() - timedelta(seconds=100)
    open_id = activity_service.create_activity(
        "AppP",
        "AppP.exe",
        "OpenWindow",
        start_time=open_start.strftime(TIME_FORMAT),
        project_id=pid,
    )
    assert activity_service.get_activity(open_id)["project_name"] == "P"

    # 3. Snapshot: persisted_open pointing at the open activity.
    _set_snapshot(
        _snapshot(
            elapsed_seconds=100,
            extra_seconds=0,
            is_persisted=True,
            persisted_activity_id=open_id,
            start_time=open_start.strftime(TIME_FORMAT),
            display_project=_project_dict(
                name="P",
                project_id=pid,
                description="P description",
                source="folder_rule",
            ),
        )
    )

    bundle = bridge.get_overview()
    assert bundle["ok"] is True

    # 4. The Overview recent row for the merged session must preserve
    #    activity_ids and first_activity_id.
    recent_row = None
    for row in bundle["activities"]:
        ids = row.get("activity_ids") or []
        if closed_id in ids and open_id in ids:
            recent_row = row
            break
    assert recent_row is not None, (
        "Overview recent row for the merged session (activity_ids covering "
        "both closed_id and open_id) must exist"
    )
    assert list(recent_row["activity_ids"]) == [closed_id, open_id], (
        "Overview recent row activity_ids must equal [closed_id, open_id] "
        "so apply_live_span_to_row can match the persisted_open anchor"
    )
    assert int(recent_row["first_activity_id"]) == closed_id, (
        "Overview recent row first_activity_id must equal closed_id (the "
        "session's first activity), NOT the open id"
    )
    # activity_id stays equal to first_activity_id (session identity).
    assert int(recent_row["activity_id"]) == closed_id

    # 5. The recent row is overlaid with the live span.
    expected_span_id = bundle["live_clock"]["display_span_id"]
    assert expected_span_id, "live_clock.display_span_id must be non-empty"
    assert recent_row["display_span_id"] == expected_span_id, (
        "Overview recent row display_span_id must equal the payload live "
        "clock's display_span_id"
    )
    assert int(recent_row["duration_seconds"]) == 160, (
        f"Overview recent row duration_seconds must equal 160 (60 closed DB "
        f"+ 100 live delta); got {recent_row['duration_seconds']}"
    )
    assert int(recent_row["live_base_seconds"]) == 160, (
        f"Overview recent row live_base_seconds must equal 160; got "
        f"{recent_row['live_base_seconds']}"
    )

    # 6. KPI totals reflect the same sample.
    assert int(bundle["today_total_seconds"]) == 160, (
        f"today_total_seconds must equal 160; got "
        f"{bundle['today_total_seconds']}"
    )
    assert int(bundle["classified_seconds"]) == 160, (
        f"classified_seconds must equal 160 (project P is classified); got "
        f"{bundle['classified_seconds']}"
    )
    assert int(bundle["uncategorized_seconds"]) == 0, (
        f"uncategorized_seconds must equal 0; got "
        f"{bundle['uncategorized_seconds']}"
    )

    # 7. current_activity shows the open activity's OWN sample (100s),
    #    NOT the session aggregate (160s). The two samples must NOT be
    #    flattened together.
    current = bundle["current_activity"]
    assert int(current["elapsed_seconds"]) == 100, (
        f"current_activity.elapsed_seconds must equal 100 (the open "
        f"activity's own sample), NOT the session aggregate 160; got "
        f"{current['elapsed_seconds']}"
    )

    # 8. Timeline session for the same activity_ids also reports 160s
    #    so Overview and Timeline agree on the session aggregate.
    timeline = bridge.get_timeline(today)
    tl_session = None
    for s in timeline["sessions"]:
        ids = s.get("activity_ids") or []
        if closed_id in ids and open_id in ids:
            tl_session = s
            break
    assert tl_session is not None, (
        "Timeline session for the merged session must exist"
    )
    assert int(tl_session["duration_seconds"]) == 160, (
        f"Timeline session duration_seconds must equal 160 (same aggregate "
        f"as Overview); got {tl_session['duration_seconds']}"
    )
    assert tl_session["display_span_id"] == expected_span_id


def test_session_to_overview_row_preserves_activity_ids_for_live_anchor_matching():
    """Low-level guard: ``_session_to_overview_row`` MUST propagate
    ``activity_ids`` and ``first_activity_id`` from the source session so
    ``apply_live_span_to_row`` can match a persisted_open anchor that is
    not the session's first activity. ``activity_id`` MUST stay equal to
    ``first_activity_id`` (session identity); the live overlay matches via
    ``activity_ids`` membership, not via ``activity_id`` equality.
    """
    from worktrace.services.view_model_service import _session_to_overview_row

    closed_id = 1001
    open_id = 1002
    session = {
        "project_name": "P",
        "project_description": "P description",
        "project_id": 42,
        "start_time": "2026-07-04 09:00:00",
        "end_time": "",
        "duration_seconds": 60,
        "is_in_progress": True,
        "is_uncategorized": False,
        "activity_ids": [closed_id, open_id],
        "first_activity_id": closed_id,
        "status_summary": "mixed",
    }
    row = _session_to_overview_row(session)
    assert list(row["activity_ids"]) == [closed_id, open_id], (
        "_session_to_overview_row must preserve activity_ids so "
        "apply_live_span_to_row can match a non-first persisted_open anchor"
    )
    assert int(row["first_activity_id"]) == closed_id, (
        "_session_to_overview_row must preserve first_activity_id"
    )
    assert int(row["activity_id"]) == closed_id, (
        "_session_to_overview_row activity_id MUST stay equal to "
        "first_activity_id; do NOT change it to the open id"
    )
