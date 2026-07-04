"""Unified live-display contract tests.

These tests verify the root-cause architecture introduced to stabilize the
live display clock, refresh cycle, and open-row classification:

1. ``stable_live_key`` / ``stable_live_key_hash`` are consistent across
   Overview / Recent / Timeline / Detail for the same current snapshot.
2. ``stable_live_key`` survives the virtual → persisted_open transition.
3. ``get_refresh_state`` supports date-scoped revision via ``report_date``.
4. ``get_refresh_state`` returns unified live clock fields
   (``live_started_at_epoch_ms``, ``carry_seconds``, ``stable_live_key``).
5. Persisted open display project does not revert to unclassified.
6. Persisted open natural duration update does not change refresh_revision.
7. Manual structural changes (project edit / time edit) change refresh_revision.
8. Open-row project sync converges the persisted open DB row's project
   assignment before display so the virtual → persisted_open transition
   does not revert a concrete project to ``未归类``. Overview / Recent /
   Timeline / Detail / KPI all stay consistent. Manual assignments and
   concrete automatic assignments are NOT overridden. ``suggested_project_name``
   is honored without creating a new project. Structural project changes
   trigger ``refresh_revision``; natural duration growth does not.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from worktrace.constants import STATUS_NORMAL, TIME_FORMAT, UNCATEGORIZED_PROJECT
from worktrace.services import activity_service, folder_rule_service, project_service, settings_service
from worktrace.services.live_display_service import (
    _stable_live_key,
    _stable_live_key_hash,
    build_current_activity_summary,
)
from worktrace.services.project_inference_service import (
    assign_project_for_activity,
    get_assignment_for_activity,
    sync_persisted_open_activity_project,
)
from worktrace.services import timeline_service
from worktrace.webview_ui.bridge import WebViewBridge




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


def _normal_snapshot(
    *,
    elapsed_seconds: int = 120,
    status: str = STATUS_NORMAL,
    is_persisted: bool = False,
    persisted_activity_id: int = 0,
    inferred_project_name: str = "TestProject",
    extra_seconds: int = 0,
    start_time: str | None = None,
) -> dict:
    now = datetime.now()
    if start_time is None:
        start = now - timedelta(seconds=elapsed_seconds)
        start_time = start.strftime(TIME_FORMAT)
    return {
        "app_name": "AppA",
        "process_name": "AppA.exe",
        "inferred_project_name": inferred_project_name,
        "start_time": start_time,
        "elapsed_seconds": elapsed_seconds,
        "extra_seconds": extra_seconds,
        "status": status,
        "is_persisted": is_persisted,
        "persisted_activity_id": persisted_activity_id,
    }




def test_stable_live_key_consistent_across_overview_recent_timeline_detail(bridge):
    """Under the unified Activity Display Model, a ``persisted_open``
    snapshot must surface the SAME unified ``live_clock`` identity
    (``display_span_id``, ``stable_live_key_hash``,
    ``live_started_at_epoch_ms``) across Overview / Recent / Timeline /
    Details. The real persisted DB row in each list is overlaid with the
    same ``display_span_id`` and ``stable_live_key_hash`` via
    ``apply_live_span_to_row`` (no virtual session / virtual detail row
    is injected anymore)."""
    aid, start_time = _create_real_open_activity(elapsed_seconds=120)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=120,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )
    overview = bridge.get_overview()
    recent = bridge.get_recent_activities()
    timeline = bridge.get_timeline()
    details = bridge.get_timeline_session_details([aid], None)

    # display_span_id must be non-empty for a persisted_open snapshot.
    assert overview["live_clock"]["display_span_id"]

    # All four ViewModels must share the same stable_live_key_hash.
    assert (
        overview["live_clock"]["stable_live_key_hash"]
        == recent["live_clock"]["stable_live_key_hash"]
        == timeline["live_clock"]["stable_live_key_hash"]
        == details["live_clock"]["stable_live_key_hash"]
    )

    # live_started_at_epoch_ms must match between overview and timeline.
    assert (
        overview["live_clock"]["live_started_at_epoch_ms"]
        == timeline["live_clock"]["live_started_at_epoch_ms"]
    )

    # The persisted DB row in each list carries the same display_span_id
    # and stable_live_key_hash (via apply_live_span_to_row overlay).
    expected_span_id = overview["live_clock"]["display_span_id"]
    expected_hash = overview["live_clock"]["stable_live_key_hash"]

    # Recent: find the persisted open item by activity_id.
    recent_row = next(
        (
            item
            for item in recent["activities"]
            if int(item.get("activity_id") or 0) == aid
        ),
        None,
    )
    assert recent_row is not None, "persisted open row not found in recent"
    assert recent_row["display_span_id"] == expected_span_id
    assert recent_row["stable_live_key_hash"] == expected_hash

    # Timeline: find the persisted open session by first_activity_id.
    timeline_session = next(
        (
            s
            for s in timeline["sessions"]
            if int(s.get("first_activity_id") or 0) == aid
        ),
        None,
    )
    assert timeline_session is not None, "persisted open session not found in timeline"
    assert timeline_session["display_span_id"] == expected_span_id
    assert timeline_session["stable_live_key_hash"] == expected_hash

    # Details: find the persisted open detail row by activity_id.
    detail_row = next(
        (
            a
            for a in details["activities"]
            if int(a.get("activity_id") or 0) == aid
        ),
        None,
    )
    assert detail_row is not None, "persisted open detail row not found"
    assert detail_row["display_span_id"] == expected_span_id
    assert detail_row["stable_live_key_hash"] == expected_hash




def test_stable_live_key_survives_virtual_to_persisted_transition(bridge):
    """the same activity transitioning from virtual
    (unpersisted) to persisted_open must keep the same stable_live_key so
    the frontend continuity key does not break.

    ``_stable_live_key`` excludes ``is_persisted`` / ``persisted_activity_id``
    / ``inferred_project_name`` so only the display-safe identity
    (resource / app / start_time / status) determines the key."""
    start = (datetime.now() - timedelta(seconds=45)).strftime(TIME_FORMAT)
    virtual_snapshot = _normal_snapshot(
        elapsed_seconds=45, is_persisted=False, start_time=start
    )
    persisted_snapshot = _normal_snapshot(
        elapsed_seconds=45, is_persisted=True, persisted_activity_id=42, start_time=start
    )

    key_virtual = _stable_live_key(virtual_snapshot)
    key_persisted = _stable_live_key(persisted_snapshot)
    assert key_virtual == key_persisted, (
        "stable_live_key must not change when only is_persisted / "
        "persisted_activity_id change"
    )

    hash_virtual = _stable_live_key_hash(virtual_snapshot)
    hash_persisted = _stable_live_key_hash(persisted_snapshot)
    assert hash_virtual == hash_persisted


def test_stable_live_key_changes_on_start_time_change(bridge):
    """when the start_time changes (a genuinely
    different activity), the stable_live_key must also change."""
    s1 = _normal_snapshot(elapsed_seconds=10, start_time="2026-07-01 10:00:00")
    s2 = _normal_snapshot(elapsed_seconds=20, start_time="2026-07-01 11:00:00")
    assert _stable_live_key(s1) != _stable_live_key(s2)




def test_get_refresh_state_returns_unified_live_clock_fields(bridge):
    """``get_refresh_state`` must return the unified
    live clock fields so the frontend ticker can use scheme A
    (``carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)``)
    anchored on a stable start-time anchor."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    state = bridge.get_refresh_state()
    assert state["ok"] is True
    for field in (
        "live_started_at_epoch_ms",
        "carry_seconds",
        "stable_live_key",
        "stable_live_key_hash",
        "live_state",
        "report_date",
    ):
        assert field in state, (
            "get_refresh_state missing unified live clock field: " + field
        )
    # When a normal unpersisted snapshot is active, live_started_at_epoch_ms
    # must be non-zero (derived from start_time).
    assert int(state["live_started_at_epoch_ms"]) > 0




def test_get_refresh_state_accepts_report_date(bridge):
    """``get_refresh_state`` must accept an optional
    ``report_date`` parameter so the revision is scoped to the viewed
    date. A structural change on a past date must be detectable even when
    today's revision is unchanged."""
    # Call without report_date (default: today)
    state_default = bridge.get_refresh_state()
    assert state_default["ok"] is True
    assert "refresh_revision" in state_default

    # Call with an explicit past date
    state_scoped = bridge.get_refresh_state("2026-01-01")
    assert state_scoped["ok"] is True
    assert "refresh_revision" in state_scoped
    assert state_scoped["report_date"] == "2026-01-01"


def test_get_refresh_state_bridge_method_accepts_report_date(bridge):
    """the bridge method signature must accept
    ``report_date`` and pass it through to the API."""
    # The bridge method must accept the parameter without error.
    result = bridge.get_refresh_state(report_date="2026-06-15")
    assert result["ok"] is True
    assert result["report_date"] == "2026-06-15"




def _create_real_open_activity(
    *,
    app_name: str = "AppA",
    process_name: str = "AppA.exe",
    window_title: str = "Window",
    file_path_hint: str | None = None,
    elapsed_seconds: int = 120,
) -> tuple[int, str]:
    """Create a real open (``end_time IS NULL``) activity row and return
    ``(activity_id, start_time)``.

    The row defaults to the uncategorized project (matching
    ``create_activity`` behavior when no ``project_id`` is passed). The
    ``start_time`` is set to ``now - elapsed_seconds`` so the snapshot
    can carry a positive elapsed value.
    """
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


def test_persisted_open_display_project_does_not_revert(bridge):
    """(defensive fallback path): when a real
    persisted open DB row is uncategorized AND has no
    ``suggested_project_name``, ``_display_project_name`` falls back to
    the snapshot's ``inferred_project_name`` so the display does not
    revert to ``未归类`` during the window between ``create_activity``
    and a successful open-row sync.

    This is the DEFENSIVE fallback only. The primary path — where the
    open-row sync assigns a concrete DB project that the display reads
    directly — is covered by
    ``test_persisted_open_display_project_does_not_revert_with_real_uncategorized_row``.
    ``_display_project_name`` does NOT unconditionally prefer the
    snapshot's inferred name; it only falls back to it when the DB row
    is uncategorized and has no suggested name.
    """
    aid, start_time = _create_real_open_activity(elapsed_seconds=60)
    # The row is uncategorized (create_activity default) with no
    # suggested_project_name (plain app, no anchor file).
    row = activity_service.get_activity(aid)
    assert row["project_name"] == UNCATEGORIZED_PROJECT
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=60,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="DefensiveFallbackProject",
            start_time=start_time,
        )
    )
    summary = build_current_activity_summary(
        json.loads(
            settings_service.get_setting("current_activity_snapshot") or "null"
        )
    )
    assert summary["project_name"] == "DefensiveFallbackProject"
    assert not summary["is_uncategorized"]




def test_persisted_open_display_project_does_not_revert_with_real_uncategorized_row(bridge):
    """a real persisted open DB row that starts
    uncategorized must be converged to a concrete project by the
    open-row sync helper (``sync_persisted_open_activity_project``)
    BEFORE the display reads it. After the sync,
    ``build_current_activity_summary`` reads the concrete DB
    ``project_name`` directly (step 1 of the resolution order) — not the
    snapshot's defensive fallback.

    This replaces the previous false-positive test that set
    ``persisted_activity_id=1`` without creating a real DB row (so the
    display naturally fell back to the snapshot's inferred name). This
    test creates a real uncategorized open row, runs the sync with a
    folder-rule fixture, and asserts the DB row itself is classified.
    """
    pid = project_service.create_project("MyProject")
    folder_rule_service.create_or_update_folder_rule("D:\\MyProject", pid)
    aid, start_time = _create_real_open_activity(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title="main.py - Visual Studio Code",
        file_path_hint="D:\\MyProject\\main.py",
        elapsed_seconds=60,
    )
    # Pre-sync: the row is uncategorized.
    assert activity_service.get_activity(aid)["project_name"] == UNCATEGORIZED_PROJECT

    # Run the open-row project sync — this delegates to
    # ``assign_project_for_activity`` which resolves the folder rule.
    assignment = sync_persisted_open_activity_project(aid)
    assert assignment["source"] == "folder_rule"
    assert int(assignment["project_id"]) == pid

    # The DB row is now concrete.
    assert activity_service.get_activity(aid)["project_name"] == "MyProject"

    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=60,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="MyProject",
            start_time=start_time,
        )
    )
    summary = build_current_activity_summary(
        json.loads(
            settings_service.get_setting("current_activity_snapshot") or "null"
        )
    )
    assert summary["project_name"] == "MyProject"
    assert summary["is_uncategorized"] is False


def test_persisted_open_timeline_recent_detail_and_overview_classification_consistent(bridge):
    """after the open-row sync
    assigns a concrete project, Overview / Recent / Timeline / Detail
    must ALL display the concrete project, and the Overview KPI must
    count the live duration as classified (not uncategorized).

    The persisted open row's live seconds come from
    ``timeline_service._live_duration_for_row`` (which reads the
    snapshot), so the session duration already includes the live time.
    Statistics is DB-only, so the only live contribution to the KPI is
    via the real DB session.
    """
    pid = project_service.create_project("MyProject")
    folder_rule_service.create_or_update_folder_rule("D:\\MyProject", pid)
    aid, start_time = _create_real_open_activity(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title="main.py - Visual Studio Code",
        file_path_hint="D:\\MyProject\\main.py",
        elapsed_seconds=120,
    )
    sync_persisted_open_activity_project(aid)
    assert activity_service.get_activity(aid)["project_name"] == "MyProject"

    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=120,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="MyProject",
            start_time=start_time,
        )
    )
    today = timeline_service.get_default_report_date()

    # Overview: current activity project + KPI.
    overview = bridge.get_overview()
    assert overview["ok"] is True
    assert overview["current_activity"]["project_name"] == "MyProject"
    assert overview["current_activity"]["is_uncategorized"] is False
    # The live duration (120s) must be classified, not uncategorized.
    assert int(overview["classified_seconds"]) >= 120
    assert int(overview["uncategorized_seconds"]) == 0

    # Recent: the persisted open item must show the concrete project.
    recent = bridge.get_recent_activities()
    assert recent["ok"] is True
    persisted_items = [
        item for item in recent["activities"]
        if int(item.get("activity_id") or 0) == aid
    ]
    assert persisted_items, "persisted open activity must appear in recent"
    assert persisted_items[0]["project_name"] == "MyProject"

    # Timeline: the persisted open session must show the concrete project.
    timeline = bridge.get_timeline(today)
    assert timeline["ok"] is True
    persisted_sessions = [
        s for s in timeline["sessions"]
        if aid in (s.get("activity_ids") or [])
    ]
    assert persisted_sessions, "persisted open activity must appear in timeline"
    assert persisted_sessions[0]["project_name"] == "MyProject"
    assert persisted_sessions[0]["is_uncategorized"] is False

    # Detail: the persisted open detail row must show the concrete project.
    details = bridge.get_timeline_session_details([aid], today)
    assert details["ok"] is True
    assert len(details["activities"]) >= 1
    detail_row = details["activities"][0]
    assert detail_row["project_name"] == "MyProject"


def test_open_project_sync_does_not_override_manual_assignment(bridge):
    """Acceptance 7: the open-row sync must NOT override a manual
    assignment. When the activity has ``manual_override=1`` and the
    assignment ``is_manual=1``, the sync helper returns the current
    assignment unchanged.
    """
    manual_pid = project_service.create_project("ManualProject")
    aid, start_time = _create_real_open_activity(elapsed_seconds=60)
    # Manually assign to ManualProject.
    activity_service.update_activity_project(aid, manual_pid, manual=True)
    assert activity_service.get_activity(aid)["project_name"] == "ManualProject"

    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=60,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="OtherProject",
            start_time=start_time,
        )
    )
    # Run the sync — must be a no-op because manual_override=1.
    assignment = sync_persisted_open_activity_project(aid)
    assert assignment["source"] == "manual"
    assert int(assignment["is_manual"]) == 1
    assert int(assignment["project_id"]) == manual_pid

    # DB row still shows the manual project.
    assert activity_service.get_activity(aid)["project_name"] == "ManualProject"

    # Display reads the concrete DB project (step 1 of resolution).
    summary = build_current_activity_summary(
        json.loads(
            settings_service.get_setting("current_activity_snapshot") or "null"
        )
    )
    assert summary["project_name"] == "ManualProject"
    assert summary["is_uncategorized"] is False


def test_open_project_sync_does_not_change_concrete_db_assignment(bridge):
    """Acceptance 8: the open-row sync must NOT re-run inference on an
    already-concrete automatic assignment (``folder_rule`` /
    ``keyword_rule`` / ``midnight_anchor``). This prevents an in-flight
    activity from flapping between projects on every collector tick.
    """
    concrete_pid = project_service.create_project("ConcreteProject")
    folder_rule_service.create_or_update_folder_rule("D:\\ConcreteProject", concrete_pid)
    aid, start_time = _create_real_open_activity(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title="main.py - Visual Studio Code",
        file_path_hint="D:\\ConcreteProject\\main.py",
        elapsed_seconds=60,
    )
    # Assign a concrete automatic assignment directly (folder_rule).
    assignment = assign_project_for_activity(aid)
    assert assignment["source"] == "folder_rule"
    assert int(assignment["project_id"]) == concrete_pid

    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=60,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="DifferentProject",
            start_time=start_time,
        )
    )
    # Run the sync — must be a no-op because source is "folder_rule"
    # (not in _OPEN_ROW_UNCLASSIFIED_SOURCES).
    assignment2 = sync_persisted_open_activity_project(aid)
    assert assignment2["source"] == "folder_rule"
    assert int(assignment2["project_id"]) == concrete_pid

    # DB row still shows the concrete project.
    assert activity_service.get_activity(aid)["project_name"] == "ConcreteProject"

    # Display reads the concrete DB project (step 1 of resolution).
    summary = build_current_activity_summary(
        json.loads(
            settings_service.get_setting("current_activity_snapshot") or "null"
        )
    )
    assert summary["project_name"] == "ConcreteProject"
    assert summary["is_uncategorized"] is False


def test_open_project_sync_triggers_refresh_revision_once_for_structural_project_change(bridge):
    """Acceptance 10-11: a structural project change (uncategorized →
    concrete via the open-row sync) must trigger ``refresh_revision``.
    A subsequent natural duration update (``set_activity_duration``)
    must NOT trigger another revision change because
    ``duration_seconds`` is excluded from the per-row structural
    signature.
    """
    pid = project_service.create_project("MyProject")
    folder_rule_service.create_or_update_folder_rule("D:\\MyProject", pid)
    aid, start_time = _create_real_open_activity(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title="main.py - Visual Studio Code",
        file_path_hint="D:\\MyProject\\main.py",
        elapsed_seconds=120,
    )
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=120,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="MyProject",
            start_time=start_time,
        )
    )
    # r1: DB row is uncategorized.
    r1 = bridge.get_refresh_state()["refresh_revision"]

    # Structural change: sync assigns concrete project (project_id changes).
    sync_persisted_open_activity_project(aid)
    assert activity_service.get_activity(aid)["project_name"] == "MyProject"
    r2 = bridge.get_refresh_state()["refresh_revision"]
    assert r1 != r2, (
        "refresh_revision must change when the open-row sync structurally "
        "reassigns the project from uncategorized to concrete"
    )

    # Natural duration growth: must NOT change the revision.
    activity_service.set_activity_duration(aid, 9999)
    r3 = bridge.get_refresh_state()["refresh_revision"]
    assert r2 == r3, (
        "refresh_revision must not change on a natural duration update "
        "(duration_seconds is excluded from the structural signature)"
    )


def test_open_project_sync_supports_suggested_project_name_without_creating_project(bridge):
    """Acceptance 9: when the open-row sync can only infer a
    ``suggested_project_name`` (no folder / keyword rule matches, but
    the resource is an anchor file with a parent folder), the helper
    writes ``source = "suggested_project_name"`` with the suggested
    name while ``project_id`` stays uncategorized. No new project is
    created. Timeline / Recent / Detail display the suggested name via
    ``_attach_display_project`` (which honors ``suggested_project_name``
    when ``project_id == uncategorized_id``).
    """
    # Use a path with NO matching folder rule and NO keyword rule.
    # The anchor file's parent folder name becomes the suggested project.
    aid, start_time = _create_real_open_activity(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title="main.py - Visual Studio Code",
        file_path_hint="D:\\Repo\\SuggestedProject\\main.py",
        elapsed_seconds=120,
    )
    # Pre-sync: uncategorized.
    assert activity_service.get_activity(aid)["project_name"] == UNCATEGORIZED_PROJECT

    assignment = sync_persisted_open_activity_project(aid)
    assert assignment["source"] == "suggested_project_name"
    assert str(assignment.get("suggested_project_name") or "") == "SuggestedProject"
    # project_id is still uncategorized.
    uncategorized_id = project_service.get_or_create_uncategorized_project()
    assert int(assignment["project_id"]) == int(uncategorized_id)

    # No new project was auto-created.
    assert project_service.get_project_by_name("SuggestedProject") is None

    # Display: _display_project_name reads the suggested name from the
    # assignment (step 2 of the resolution order).
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=120,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="SuggestedProject",
            start_time=start_time,
        )
    )
    summary = build_current_activity_summary(
        json.loads(
            settings_service.get_setting("current_activity_snapshot") or "null"
        )
    )
    assert summary["project_name"] == "SuggestedProject"
    assert summary["is_uncategorized"] is False

    # Timeline / Recent / Detail also display the suggested name via
    # _attach_display_project.
    today = timeline_service.get_default_report_date()
    timeline = bridge.get_timeline(today)
    persisted_sessions = [
        s for s in timeline["sessions"]
        if aid in (s.get("activity_ids") or [])
    ]
    assert persisted_sessions
    assert persisted_sessions[0]["project_name"] == "SuggestedProject"

    recent = bridge.get_recent_activities()
    persisted_items = [
        item for item in recent["activities"]
        if int(item.get("activity_id") or 0) == aid
    ]
    assert persisted_items
    assert persisted_items[0]["project_name"] == "SuggestedProject"

    details = bridge.get_timeline_session_details([aid], today)
    assert details["activities"][0]["project_name"] == "SuggestedProject"




def test_persisted_open_natural_duration_does_not_change_revision(bridge):
    """a persisted open row's natural duration
    growth (via ``set_activity_duration``) must NOT change
    ``refresh_revision``. The revision excludes ``duration_seconds`` and
    ``updated_at`` from the per-row structural signature."""
    from worktrace.services import activity_service

    # Use today's date so the activity is included in the default
    # report_date scope of ``get_refresh_state``.
    today = datetime.now().strftime("%Y-%m-%d")
    # Insert a closed activity so the revision has a baseline.
    aid = activity_service.create_activity(
        "App", "App.exe", "Spec", start_time=f"{today} 09:00:00"
    )
    activity_service.close_activity(aid, f"{today} 09:30:00")
    r1 = bridge.get_refresh_state()["refresh_revision"]

    # Update the duration (natural growth) — this should NOT change the
    # revision because duration_seconds is excluded from the structural
    # signature.
    activity_service.set_activity_duration(aid, 1801)
    r2 = bridge.get_refresh_state()["refresh_revision"]
    assert r1 == r2, (
        "refresh_revision must not change when only duration_seconds / "
        "updated_at change (natural growth)"
    )


def test_manual_project_edit_changes_revision(bridge):
    """a manual project assignment change must change
    ``refresh_revision``."""
    from worktrace.services import activity_service, project_service

    today = datetime.now().strftime("%Y-%m-%d")
    aid = activity_service.create_activity(
        "App", "App.exe", "Spec", start_time=f"{today} 09:00:00"
    )
    activity_service.close_activity(aid, f"{today} 09:30:00")
    r1 = bridge.get_refresh_state()["refresh_revision"]

    # Assign a project — a structural change.
    pid = project_service.create_project("MyProject")
    activity_service.update_activity_project(aid, pid)
    r2 = bridge.get_refresh_state()["refresh_revision"]
    assert r1 != r2, (
        "refresh_revision must change when project assignment is added"
    )


def test_time_edit_changes_revision(bridge):
    """a time edit (changing start_time / end_time)
    must change ``refresh_revision``."""
    from worktrace.services import activity_service

    today = datetime.now().strftime("%Y-%m-%d")
    aid = activity_service.create_activity(
        "App", "App.exe", "Spec", start_time=f"{today} 09:00:00"
    )
    activity_service.close_activity(aid, f"{today} 09:30:00")
    r1 = bridge.get_refresh_state()["refresh_revision"]

    # Edit the time — a structural change.
    activity_service.update_activity_time(aid, f"{today} 09:05:00", f"{today} 09:30:00")
    r2 = bridge.get_refresh_state()["refresh_revision"]
    assert r1 != r2




def test_virtual_session_and_detail_are_display_only(bridge):
    """Under the unified Activity Display Model, a normal unpersisted
    pending snapshot (``virtual_pending``) does NOT inject virtual
    sessions or virtual detail rows into Timeline / Details. The pending
    resource is ONLY visible in the current-activity area. Recent /
    Timeline / Details lists come purely from DB rows."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=10))
    timeline = bridge.get_timeline()
    # No virtual session is injected for a virtual_pending snapshot.
    assert timeline["sessions"] == []

    details = bridge.get_timeline_session_details([], None)
    # No virtual detail row is injected for an empty selection.
    assert details["activities"] == []

    # The current-activity area DOES show the pending resource.
    overview = bridge.get_overview()
    assert overview["current_activity"]["active"] is True
    assert overview["current_activity"]["live_state"] in (
        "virtual_pending",
        "absorbed_pending",
    )




def test_timeline_service_no_datetime_now_fallback():
    """``timeline_service._display_duration`` must
    NOT use ``datetime.now() - start_time`` as a fallback for open rows.
    The unified live clock (``live_display_service``) is the only source
    of live duration."""
    from worktrace.services import timeline_service

    # An open row with no stored duration_seconds and no live-duration
    # match must return 0, not a wall-clock calculation.
    row = {
        "is_in_progress": True,
        "start_time": "2026-07-01 09:00:00",
        "duration_seconds": None,
    }
    result = timeline_service._display_duration(row)
    assert result == 0, (
        "Open row without stored duration or live match must return 0, "
        "not a datetime.now() - start_time calculation"
    )




def test_persisted_open_recent_item_carries_stable_live_fields(bridge):
    """persisted_open DB rows in
    ``get_recent_activities`` must carry the same stable live fields
    (``stable_live_key_hash``, ``live_started_at_epoch_ms``,
    ``carry_seconds``, ``live_state``) as virtual rows so the frontend
    continuity key survives the virtual → persisted_open transition."""
    aid, start_time = _create_real_open_activity(
        app_name="AppA",
        process_name="AppA.exe",
        elapsed_seconds=60,
    )
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=60,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )
    recent = bridge.get_recent_activities()
    assert recent["ok"] is True

    # Find the persisted_open DB item (it has activity_id == aid).
    persisted_item = None
    for item in recent["activities"]:
        if int(item.get("activity_id") or 0) == aid:
            persisted_item = item
            break
    assert persisted_item is not None, "persisted_open DB row not found in recent activities"

    # The persisted_open row must carry stable_live_key_hash.
    assert persisted_item["stable_live_key_hash"], (
        "persisted_open recent item must carry stable_live_key_hash"
    )
    assert persisted_item["live_state"] == "persisted_open"
    assert int(persisted_item["live_started_at_epoch_ms"]) > 0

    # All live span fields added by apply_live_span_to_row must be present.
    for field in (
        "display_span_id",
        "stable_live_key_hash",
        "live_state",
        "live_started_at_epoch_ms",
        "carry_seconds",
        "live_base_seconds",
        "live_delta_eligible",
    ):
        assert field in persisted_item, (
            "persisted_open recent item missing live span field: " + field
        )


def test_persisted_open_timeline_session_carries_stable_live_fields(bridge):
    """persisted_open DB sessions in
    ``get_timeline`` must carry the same stable live fields as virtual
    sessions."""
    aid, start_time = _create_real_open_activity(
        app_name="AppA",
        process_name="AppA.exe",
        elapsed_seconds=60,
    )
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=60,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )
    timeline = bridge.get_timeline()
    assert timeline["ok"] is True

    # Find the persisted_open DB session (it has first_activity_id == aid).
    persisted_session = None
    for s in timeline["sessions"]:
        if int(s.get("first_activity_id") or 0) == aid:
            persisted_session = s
            break
    assert persisted_session is not None, "persisted_open DB session not found in timeline"

    assert persisted_session["stable_live_key_hash"], (
        "persisted_open timeline session must carry stable_live_key_hash"
    )
    assert persisted_session["live_state"] == "persisted_open"

    # All live span fields added by apply_live_span_to_row must be present.
    for field in (
        "display_span_id",
        "stable_live_key_hash",
        "live_state",
        "live_started_at_epoch_ms",
        "carry_seconds",
        "live_base_seconds",
        "live_delta_eligible",
    ):
        assert field in persisted_session, (
            "persisted_open timeline session missing live span field: " + field
        )


def test_persisted_open_detail_row_carries_stable_live_fields(bridge):
    """persisted_open DB detail rows in
    ``get_timeline_session_details`` must carry the same stable live
    fields as virtual detail rows."""
    aid, start_time = _create_real_open_activity(
        app_name="AppA",
        process_name="AppA.exe",
        elapsed_seconds=60,
    )
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=60,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )
    details = bridge.get_timeline_session_details([aid], None)
    assert details["ok"] is True

    # Find the persisted_open DB detail row.
    persisted_detail = None
    for a in details["activities"]:
        if int(a.get("activity_id") or 0) == aid:
            persisted_detail = a
            break
    assert persisted_detail is not None, "persisted_open DB detail row not found"

    assert persisted_detail["stable_live_key_hash"], (
        "persisted_open detail row must carry stable_live_key_hash"
    )
    assert persisted_detail["live_state"] == "persisted_open"

    # All live span fields added by apply_live_span_to_row must be present.
    for field in (
        "display_span_id",
        "stable_live_key_hash",
        "live_state",
        "live_started_at_epoch_ms",
        "carry_seconds",
        "live_base_seconds",
        "live_delta_eligible",
    ):
        assert field in persisted_detail, (
            "persisted_open detail row missing live span field: " + field
        )


def test_virtual_to_persisted_open_stable_key_hash_unchived_at_bridge(bridge):
    """The ``stable_live_key_hash`` must be identical for the
    ``virtual_pending`` state and the ``persisted_open`` state when only
    ``is_persisted`` / ``persisted_activity_id`` change. This is the
    bridge-level version of
    ``test_stable_live_key_survives_virtual_to_persisted_transition``.

    Under the new architecture, ``virtual_pending`` is ONLY visible in
    the current-activity area (no recent / timeline row is injected),
    while ``persisted_open`` is visible in the current-activity area
    AND in timeline (real DB row overlaid). The
    ``stable_live_key_hash`` surfaced via the current-activity area must
    be the same in both states so the frontend continuity key survives
    the transition.
    """
    aid, start_time = _create_real_open_activity(
        app_name="AppA",
        process_name="AppA.exe",
        elapsed_seconds=10,
    )
    # virtual_pending snapshot (unpersisted) — no DB row visible in lists.
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            is_persisted=False,
            start_time=start_time,
        )
    )
    overview_virtual = bridge.get_overview()
    virtual_hash = overview_virtual["current_activity"]["stable_live_key_hash"]
    assert virtual_hash, "virtual_pending current_activity must carry stable_live_key_hash"

    # persisted_open snapshot (same activity identity).
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )
    overview_persisted = bridge.get_overview()
    persisted_hash = overview_persisted["current_activity"]["stable_live_key_hash"]
    assert persisted_hash, "persisted_open current_activity must carry stable_live_key_hash"

    # The stable_live_key_hash must be identical across the transition.
    assert virtual_hash == persisted_hash, (
        "stable_live_key_hash must not change across virtual_pending -> persisted_open"
    )

    # persisted_open IS visible in timeline, so timeline's live_clock
    # must carry the same hash.
    timeline = bridge.get_timeline()
    assert timeline["live_clock"]["stable_live_key_hash"] == persisted_hash


# Math-invariant tests for the unified live duration contract (30s drift /
# page-switch jump / total freeze-then-jump root-cause fix).


def test_persisted_open_extra_seconds_carry_invariant(bridge):
    """``persisted_open`` must preserve ``extra_seconds`` via
    ``carry_seconds`` so the frontend formula
    ``carry_seconds + floor((now - live_started_at_epoch_ms) / 1000)``
    equals ``elapsed + extra == duration_seconds_at_sample`` at sample
    time, and ``duration_seconds_at_sample + 5`` five seconds later.

    This is the root-cause fix for the ~30s drift: previously the carry
    was hard-coded to 0 while ``duration_seconds_at_sample`` included
    ``extra_seconds``, so the frontend ``liveSeconds(clock)`` lost the
    extra seconds.
    """
    from worktrace.services.activity_display_model_service import build_activity_display_model
    from worktrace.services.live_time_service import (
        snapshot_elapsed_seconds,
        snapshot_extra_seconds,
    )

    aid, start_time = _create_real_open_activity(elapsed_seconds=210)
    snapshot = _normal_snapshot(
        elapsed_seconds=210,
        extra_seconds=30,
        is_persisted=True,
        persisted_activity_id=aid,
        start_time=start_time,
    )
    _set_snapshot(snapshot)

    model = build_activity_display_model()
    live_clock = model["live_clock"]

    assert live_clock["live_state"] == "persisted_open"
    assert live_clock["carry_seconds"] == snapshot_extra_seconds(snapshot), (
        "persisted_open carry_seconds must equal snapshot extra_seconds "
        "or the frontend liveSeconds formula loses the extra seconds"
    )
    assert live_clock["duration_seconds_at_sample"] == (
        snapshot_elapsed_seconds(snapshot) + snapshot_extra_seconds(snapshot)
    ), (
        "persisted_open duration_seconds_at_sample must equal "
        "snapshot_elapsed + snapshot_extra"
    )
    assert live_clock["duration_seconds_at_sample"] == 240

    # JS formula: live_span_seconds(T) = carry + floor((T - live_started_at)/1000).
    import time

    live_started_ms = int(live_clock["live_started_at_epoch_ms"])
    carry = int(live_clock["carry_seconds"])
    now_ms = int(time.time() * 1000)
    floor_term_now = (now_ms - live_started_ms) // 1000
    live_seconds_now = carry + floor_term_now
    assert 238 <= live_seconds_now <= 245, (
        f"live_span_seconds at sample time expected ~240, got {live_seconds_now}"
    )
    floor_term_plus_5 = ((now_ms + 5000) - live_started_ms) // 1000
    live_seconds_plus_5 = carry + floor_term_plus_5
    assert live_seconds_plus_5 - live_seconds_now == 5, (
        "live_span_seconds must advance by exactly 5 over 5 seconds"
    )

    delta_now = max(0, live_seconds_now - int(live_clock["duration_seconds_at_sample"]))
    assert 0 <= delta_now <= 5, (
        f"live delta at sample time expected ~0, got {delta_now}"
    )


def test_persisted_open_viewmodel_same_sample_consistency(bridge):
    """Under one ``persisted_open`` snapshot with ``extra_seconds=30``,
    Overview / Recent / Timeline / Detail must all share the same
    ``duration_seconds_at_sample == 240`` and the same
    ``stable_live_key_hash`` / ``display_span_id``.

    This nails down the "same sample" consistency that previously broke
    when Overview KPI used the old live projection while the other views
    used the Activity Display Model.
    """
    aid, start_time = _create_real_open_activity(elapsed_seconds=210)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=210,
            extra_seconds=30,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )

    overview = bridge.get_overview()
    recent = bridge.get_recent_activities()
    timeline = bridge.get_timeline()
    details = bridge.get_timeline_session_details([aid], None)

    expected_span_id = overview["live_clock"]["display_span_id"]
    expected_hash = overview["live_clock"]["stable_live_key_hash"]
    expected_durations = overview["live_clock"]["duration_seconds_at_sample"]
    assert expected_durations == 240

    # All four views share the same live_clock identity.
    for view_name, view in (
        ("overview", overview),
        ("recent", recent),
        ("timeline", timeline),
        ("details", details),
    ):
        assert view["live_clock"]["display_span_id"] == expected_span_id, (
            f"{view_name} live_clock.display_span_id mismatch"
        )
        assert view["live_clock"]["stable_live_key_hash"] == expected_hash, (
            f"{view_name} live_clock.stable_live_key_hash mismatch"
        )
        assert (
            view["live_clock"]["duration_seconds_at_sample"] == expected_durations
        ), f"{view_name} live_clock.duration_seconds_at_sample mismatch"

    # Detail row sample duration must be 240 (the open activity's own
    # duration at sample).
    detail_row = next(
        (a for a in details["activities"] if int(a.get("activity_id") or 0) == aid),
        None,
    )
    assert detail_row is not None
    assert detail_row["duration_seconds_at_sample"] == 240
    assert detail_row["live_base_seconds"] == 240
    assert detail_row["display_span_id"] == expected_span_id

    # Recent matching row must also carry the same span id and a live base.
    recent_row = next(
        (r for r in recent["activities"] if int(r.get("activity_id") or 0) == aid),
        None,
    )
    assert recent_row is not None
    assert recent_row["display_span_id"] == expected_span_id
    assert recent_row["live_base_seconds"] == 240

    # Timeline matching session row must also carry the same span id.
    timeline_session = next(
        (
            s
            for s in timeline["sessions"]
            if int(s.get("first_activity_id") or 0) == aid
        ),
        None,
    )
    assert timeline_session is not None
    assert timeline_session["display_span_id"] == expected_span_id

    # Timeline today_total_seconds must equal sum of session row durations
    # (post-overlay). With only this one open row, total == 240.
    sessions_total = sum(int(s.get("duration_seconds") or 0) for s in timeline["sessions"])
    assert timeline["today_total_seconds"] == sessions_total, (
        "timeline today_total_seconds must equal sum of post-overlay session "
        "durations"
    )


def test_session_base_differs_from_live_activity_duration(bridge):
    """A session row that contains BOTH a closed activity (100s) AND a
    ``persisted_open`` activity (240s) must have ``live_base_seconds``
    equal to the SESSION's full sample duration (340s), NOT the live
    activity's own duration (240s).

    The detail row for the persisted_open activity must have
    ``live_base_seconds == 240``. Both rows share the same live delta,
    so after +5s the session row reads 345s and the detail row reads
    245s. The session row must NEVER be overwritten to 245s.

    This is the regression guard against the old "every
    ``[data-display-span-id]`` node renders ``liveSeconds(clock)``"
    contract that overwrote session durations with the live activity's
    own duration.
    """
    from worktrace.services.activity_display_model_service import (
        apply_live_span_to_row,
        build_activity_display_model,
        get_live_span,
    )

    # 1. Create a closed activity of 100s in the same project.
    closed_start = datetime.now() - timedelta(seconds=400)
    closed_end = closed_start + timedelta(seconds=100)
    closed_aid = activity_service.create_activity(
        "AppA",
        "AppA.exe",
        "Window",
        start_time=closed_start.strftime(TIME_FORMAT),
    )
    activity_service.close_activity(closed_aid, closed_end.strftime(TIME_FORMAT), 100)

    # 2. Create a persisted_open activity of 240s in the same project.
    open_aid, open_start = _create_real_open_activity(elapsed_seconds=240)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=210,
            extra_seconds=30,
            is_persisted=True,
            persisted_activity_id=open_aid,
            start_time=open_start,
        )
    )

    model = build_activity_display_model()
    span = get_live_span(model)
    assert span is not None, "persisted_open display span must exist"

    # Session row aggregates both activities: 100 (closed) + 240 (live) = 340.
    session_row = {
        "session_id": "sess-1",
        "first_activity_id": open_aid,
        "activity_ids": [closed_aid, open_aid],
        "duration_seconds": 340,
        "raw_duration_seconds": 340,
    }
    detail_row = {
        "activity_id": open_aid,
        "duration_seconds": 240,
        "raw_duration_seconds": 0,
    }

    apply_live_span_to_row(session_row, span)
    apply_live_span_to_row(detail_row, span)

    assert detail_row["live_base_seconds"] == 240, (
        "detail row live_base_seconds must equal the open activity's "
        "sample duration (240)"
    )
    assert session_row["live_base_seconds"] == 340, (
        "session row live_base_seconds must equal the session's full sample "
        "duration (340 = 100 closed + 240 live), NOT the live activity's "
        "own duration (240). This is the regression guard against the old "
        "contract that overwrote session durations with liveSeconds(clock)."
    )

    assert session_row["display_span_id"] == detail_row["display_span_id"]
    assert session_row["stable_live_key_hash"] == detail_row["stable_live_key_hash"]
    assert session_row["duration_seconds_at_sample"] == 240

    # Ticker: delta = max(0, live_span_now - 240). At sample time delta=0;
    # at +5s delta=5. Session renders 340→345, detail renders 240→245.
    delta_at_sample = 0
    assert session_row["live_base_seconds"] + delta_at_sample == 340
    assert detail_row["live_base_seconds"] + delta_at_sample == 240

    delta_plus_5 = 5
    assert session_row["live_base_seconds"] + delta_plus_5 == 345, (
        "session row after +5s must be 345, NOT 245 — the session must not "
        "be overwritten to the live activity's own duration"
    )
    assert detail_row["live_base_seconds"] + delta_plus_5 == 245


def test_virtual_pending_no_rows_in_lists_and_no_kpi_tick(bridge):
    """A ``virtual_pending`` snapshot (normal, unpersisted, <30s, no
    absorb anchor) must:

    * render the pending resource in the current-activity area;
    * NOT inject any row into Recent / Timeline / Details;
    * NOT inflate Overview KPI ``today_total_seconds`` /
      ``classified_seconds`` / ``uncategorized_seconds`` (no DB row to
      project onto);
    * surface a live_clock with ``is_live == True`` but
      ``is_project_duration_live == False``.
    """
    # No prior activity exists, so the pending snapshot has no anchor.
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            extra_seconds=0,
            is_persisted=False,
        )
    )

    overview = bridge.get_overview()
    recent = bridge.get_recent_activities()
    timeline = bridge.get_timeline()

    # current_activity area IS active.
    assert overview["current_activity"]["active"] is True
    assert overview["current_activity"]["is_virtual_live"] is True
    assert overview["live_clock"]["live_state"] == "virtual_pending"
    assert overview["live_clock"]["is_live"] is True
    # KPI totals must NOT tick for virtual_pending.
    assert overview["live_clock"]["is_project_duration_live"] is False, (
        "virtual_pending must NOT tick project/KPI totals"
    )

    # Recent / Timeline must have NO live row injected.
    assert recent["activities"] == [], (
        "virtual_pending must NOT inject a row into Recent"
    )
    assert timeline["sessions"] == [], (
        "virtual_pending must NOT inject a row into Timeline"
    )

    # KPI totals must be 0 (no DB rows, no live projection onto a DB row).
    assert int(overview["today_total_seconds"]) == 0
    assert int(overview["classified_seconds"]) == 0
    assert int(overview["uncategorized_seconds"]) == 0


def test_absorbed_pending_overlays_anchor_row_only(bridge):
    """An ``absorbed_pending`` snapshot (normal, unpersisted, <30s, WITH
    absorb anchor in the SAME session) must:

    * overlay ONLY the anchor DB row's live clock fields (no virtual row
      injection);
    * set the anchor row's ``live_base_seconds`` = ``anchor_raw +
      pending_at_sample`` so the frontend ticker lands on the right value;
    * NOT write the DB (anchor row's stored duration is unchanged in DB);
    * keep the anchor row's project / resource identity (the pending
      snapshot's inferred project is NOT overlaid).

    Absorption no longer relies on the legacy structured
    ``short_activity_carry`` JSON (it was removed — no production
    writer). The anchor is resolved purely from today's DB rows that
    pass the boundary-aware ``_is_absorbable_anchor`` gate: closed,
    auto, normal, ``end_time <= pending_start_time``, no session
    boundary in ``[anchor.end_time, pending_start_time]``.
    """
    # 1. Create a closed anchor activity of 60s.
    anchor_start = datetime.now() - timedelta(seconds=120)
    anchor_end = anchor_start + timedelta(seconds=60)
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start.strftime(TIME_FORMAT),
    )
    activity_service.close_activity(anchor_aid, anchor_end.strftime(TIME_FORMAT), 60)

    # 2. Set a <30s pending snapshot starting AFTER the anchor closed
    #    (same session — no boundary recorded between anchor.end_time
    #    and pending_start_time).
    pending_start = datetime.now() - timedelta(seconds=10)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            extra_seconds=0,
            is_persisted=False,
            start_time=pending_start.strftime(TIME_FORMAT),
            inferred_project_name="PendingProject",
        )
    )

    overview = bridge.get_overview()
    recent = bridge.get_recent_activities()
    timeline = bridge.get_timeline()

    assert overview["live_clock"]["live_state"] == "absorbed_pending"
    assert overview["live_clock"]["is_live"] is True
    assert overview["live_clock"]["is_project_duration_live"] is True

    # No virtual row injection: only the anchor DB row appears.
    assert len(recent["activities"]) == 1, (
        "absorbed_pending must NOT inject a virtual row; only the anchor DB "
        "row appears"
    )
    recent_row = recent["activities"][0]
    assert int(recent_row["activity_id"]) == anchor_aid
    assert recent_row["live_state"] == "absorbed_pending"
    assert recent_row["source"] == "absorbed_pending"

    # Anchor row keeps its OWN project identity, not the pending snapshot's.
    assert recent_row["project_name"] == "未归类", (
        "absorbed_pending must keep the anchor row's project identity"
    )

    # live_base = anchor_raw(60) + pending_at_sample(10) = 70.
    assert recent_row["live_base_seconds"] == 70, (
        f"absorbed_pending live_base_seconds must equal anchor_raw (60) + "
        f"pending_at_sample (10) = 70, got {recent_row['live_base_seconds']}"
    )

    # DB must NOT be written: the anchor row's stored duration is still 60.
    anchor_db = activity_service.get_activity(anchor_aid)
    assert int(anchor_db["duration_seconds"]) == 60, (
        "absorbed_pending display projection must NOT write the DB"
    )

    # Timeline session for the anchor also overlays (no virtual session).
    anchor_session = next(
        (
            s
            for s in timeline["sessions"]
            if int(s.get("first_activity_id") or 0) == anchor_aid
        ),
        None,
    )
    assert anchor_session is not None
    assert anchor_session["live_state"] == "absorbed_pending"


# Boundary-aware absorption contract: a ``<30s`` pending snapshot MUST
# NOT absorb into a previous confirmed normal activity when a session
# boundary was recorded between the anchor's ``end_time`` and the
# pending snapshot's ``start_time``. Legacy carry path removed.


def test_absorbed_pending_does_not_cross_restart_boundary(bridge):
    """A ``<30s`` pending snapshot starting AFTER a ``restart`` session
    boundary MUST NOT absorb into a previous confirmed normal activity
    even if that activity is the latest closed, auto, normal row on
    ``today``. The display state collapses to ``virtual_pending`` with
    no live span overlay.
    """
    from worktrace.services import session_boundary_service
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )

    # 1. Create a closed normal auto activity A (60s).
    anchor_start = datetime.now() - timedelta(seconds=120)
    anchor_end = anchor_start + timedelta(seconds=60)
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start.strftime(TIME_FORMAT),
    )
    activity_service.close_activity(anchor_aid, anchor_end.strftime(TIME_FORMAT), 60)

    # 2. Record a session boundary (restart) AFTER anchor.end_time.
    boundary_at = anchor_end + timedelta(seconds=10)
    session_boundary_service.record_boundary(
        boundary_at.strftime(TIME_FORMAT), "restart"
    )

    # 3. Write a <30s unpersisted normal snapshot B starting after the
    #    boundary.
    pending_start = boundary_at + timedelta(seconds=5)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            extra_seconds=0,
            is_persisted=False,
            start_time=pending_start.strftime(TIME_FORMAT),
            inferred_project_name="PendingProject",
        )
    )

    # 4. build_activity_display_model(today) MUST classify as virtual_pending.
    model = build_activity_display_model()
    assert model["live_clock"]["live_state"] == "virtual_pending", (
        "a <30s pending snapshot that starts after a restart boundary MUST "
        "NOT absorb into the previous confirmed normal activity; expected "
        "live_state=virtual_pending"
    )
    assert model["display_spans"] == [], (
        "no display span should be created when a session boundary blocks "
        "absorption (virtual_pending has no DB row to overlay)"
    )

    # 5. The bridge Overview / Recent / Timeline must NOT overlay A.
    overview = bridge.get_overview()
    recent = bridge.get_recent_activities()
    timeline = bridge.get_timeline()
    assert overview["live_clock"]["live_state"] == "virtual_pending"
    assert overview["live_clock"]["is_project_duration_live"] is False
    # Recent / Timeline carry the anchor DB row (it's still today's history),
    # but it must NOT be overlaid (no live_state, no live_base_seconds bump).
    for item in recent["activities"]:
        assert item.get("live_state") != "absorbed_pending", (
            "anchor row must NOT be overlaid when a boundary blocks absorption"
        )
        # When a boundary blocks absorption, the anchor row is NOT overlaid,
        # so ``live_base_seconds`` is either absent (None) or — if some other
        # non-absorbed live_state attached a base — equal to the stored
        # ``duration_seconds`` (no inflation by pending projection).
        live_base = item.get("live_base_seconds")
        if live_base is not None:
            assert int(live_base) == int(item.get("duration_seconds") or 0), (
                "anchor row duration must NOT be inflated by pending "
                "projection when a boundary blocks absorption"
            )
    for s in timeline["sessions"]:
        assert s.get("live_state") != "absorbed_pending"


def test_absorbed_pending_does_not_cross_stopped_boundary(bridge):
    """A ``stopped`` boundary blocks absorption just like ``restart`` —
    no boundary reason is whitelisted. After a stop, a new ``<30s``
    pending activity is a fresh session and must NOT leak into the
    previous project's row.
    """
    from worktrace.services import session_boundary_service
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )

    anchor_start = datetime.now() - timedelta(seconds=120)
    anchor_end = anchor_start + timedelta(seconds=60)
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start.strftime(TIME_FORMAT),
    )
    activity_service.close_activity(anchor_aid, anchor_end.strftime(TIME_FORMAT), 60)

    boundary_at = anchor_end + timedelta(seconds=5)
    session_boundary_service.record_boundary(
        boundary_at.strftime(TIME_FORMAT), "stopped"
    )

    pending_start = boundary_at + timedelta(seconds=5)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=15,
            extra_seconds=0,
            is_persisted=False,
            start_time=pending_start.strftime(TIME_FORMAT),
        )
    )

    model = build_activity_display_model()
    assert model["live_clock"]["live_state"] == "virtual_pending"
    assert model["display_spans"] == []


def test_absorbed_pending_same_session_allows_absorption(bridge):
    """When NO session boundary was recorded between the anchor's
    ``end_time`` and the pending snapshot's ``start_time``, the
    ``<30s`` pending snapshot MUST absorb into the anchor. The display
    state is ``absorbed_pending`` and the span's ``anchor_activity_id``
    equals the anchor DB row's id.

    This test also verifies display-only projection: the anchor row's
    stored DB duration is unchanged after the display model is built.
    """
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )

    anchor_start = datetime.now() - timedelta(seconds=120)
    anchor_end = anchor_start + timedelta(seconds=60)
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start.strftime(TIME_FORMAT),
    )
    activity_service.close_activity(anchor_aid, anchor_end.strftime(TIME_FORMAT), 60)

    pending_start = anchor_end + timedelta(seconds=5)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            extra_seconds=0,
            is_persisted=False,
            start_time=pending_start.strftime(TIME_FORMAT),
        )
    )

    model = build_activity_display_model()
    assert model["live_clock"]["live_state"] == "absorbed_pending"
    assert len(model["display_spans"]) == 1
    span = model["display_spans"][0]
    assert int(span["anchor_activity_id"]) == anchor_aid

    # Display-only projection MUST NOT write the DB.
    anchor_db = activity_service.get_activity(anchor_aid)
    assert int(anchor_db["duration_seconds"]) == 60


def test_absorbed_pending_rejects_anchor_end_after_pending_start(bridge):
    """A closed anchor whose ``end_time`` is LATER than the pending
    snapshot's ``start_time`` is an overlap / anomaly and MUST NOT be
    used as an absorption anchor. Even if it is the latest closed,
    auto, normal row, the display state collapses to ``virtual_pending``
    so the UI does not double-count the overlap window.
    """
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )

    # 1. Construct a closed anchor whose end_time is AFTER the pending
    #    snapshot's start_time (overlap). anchor: 09:00:00 → 09:02:00.
    #    pending start: 09:01:30 (overlaps anchor by 30s).
    anchor_start = datetime.now() - timedelta(seconds=120)
    anchor_end = anchor_start + timedelta(seconds=120)  # 2-minute anchor
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start.strftime(TIME_FORMAT),
    )
    activity_service.close_activity(anchor_aid, anchor_end.strftime(TIME_FORMAT), 120)

    # 2. Pending snapshot starts BEFORE anchor.end_time (overlap).
    pending_start = anchor_start + timedelta(seconds=90)  # 30s before anchor.end_time
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            extra_seconds=0,
            is_persisted=False,
            start_time=pending_start.strftime(TIME_FORMAT),
        )
    )

    model = build_activity_display_model()
    # The anchor is NOT absorbable (end_time > pending_start_time), so the
    # display state collapses to virtual_pending.
    assert model["live_clock"]["live_state"] == "virtual_pending", (
        "an anchor whose end_time > pending_start_time is an overlap / "
        "anomaly and MUST NOT be used as an absorption anchor"
    )
    assert model["display_spans"] == []


def test_absorbed_pending_rejects_pending_without_start_time(bridge):
    """A pending snapshot with no ``start_time`` MUST NOT be absorbed —
    the ``_is_absorbable_anchor`` gate rejects empty ``pending_start_time``
    so a malformed snapshot cannot trigger absorption against a stale
    anchor.
    """
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )

    anchor_start = datetime.now() - timedelta(seconds=120)
    anchor_end = anchor_start + timedelta(seconds=60)
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start.strftime(TIME_FORMAT),
    )
    activity_service.close_activity(anchor_aid, anchor_end.strftime(TIME_FORMAT), 60)

    # Pending snapshot with no start_time.
    _set_snapshot(
        {
            "app_name": "AppA",
            "process_name": "AppA.exe",
            "inferred_project_name": "PendingProject",
            "start_time": "",
            "elapsed_seconds": 10,
            "extra_seconds": 0,
            "status": STATUS_NORMAL,
            "is_persisted": False,
            "persisted_activity_id": 0,
        }
    )

    model = build_activity_display_model()
    assert model["live_clock"]["live_state"] == "virtual_pending"
    assert model["display_spans"] == []


def test_absorbed_pending_current_activity_uses_anchor_project_for_kpi(bridge):
    """Under ``absorbed_pending``, the current-activity area shows the
    pending RESOURCE name (what the user is looking at) BUT the project
    attribution fields (``project_name``, ``project_id``,
    ``is_classified``, ``is_uncategorized``) MUST come from the ANCHOR
    DB row so KPI classified / uncategorized increments match the
    Recent / Timeline overlay row (which also uses the anchor's
    project). This forbids the same live span being classified as
    PendingProject in KPI and AnchorProject in Recent / Timeline.
    """
    from worktrace.services import project_service

    # 1. Create a classified project "AnchorProject".
    proj_id = int(project_service.create_project("AnchorProject", description="anchor"))

    # 2. Create a closed anchor activity attributed to AnchorProject.
    anchor_start = datetime.now() - timedelta(seconds=120)
    anchor_end = anchor_start + timedelta(seconds=60)
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start.strftime(TIME_FORMAT),
        project_id=proj_id,
    )
    activity_service.close_activity(anchor_aid, anchor_end.strftime(TIME_FORMAT), 60)

    # 3. Set a <30s pending snapshot whose inferred project is DIFFERENT
    #    ("PendingProject"). Same session (no boundary).
    pending_start = anchor_end + timedelta(seconds=5)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            extra_seconds=0,
            is_persisted=False,
            start_time=pending_start.strftime(TIME_FORMAT),
            inferred_project_name="PendingProject",
        )
    )

    overview = bridge.get_overview()
    recent = bridge.get_recent_activities()

    # current_activity's project fields MUST come from the anchor.
    current = overview["current_activity"]
    assert current["live_state"] == "absorbed_pending"
    assert current["project_name"] == "AnchorProject", (
        "current_activity.project_name must come from the anchor DB row, "
        "NOT the pending snapshot's inferred project, so KPI classification "
        "matches the Recent / Timeline overlay row"
    )
    assert int(current["project_id"]) == proj_id
    assert current["is_classified"] is True
    assert current["is_uncategorized"] is False

    # The Recent overlay row also uses the anchor's project — same span,
    # same project attribution. The overview recent-item row exposes
    # ``project_name`` (not ``project_id``); the project name match is
    # the cross-ViewModel consistency check.
    recent_row = recent["activities"][0]
    assert int(recent_row["activity_id"]) == anchor_aid
    assert recent_row["project_name"] == "AnchorProject"

    # The current-activity display text MUST contain the anchor's project
    # name (so the user sees the same project label as the Recent row),
    # while the resource name (first part) is the pending snapshot's.
    assert "AnchorProject" in current["display"]
    assert "PendingProject" not in current["display"]


def test_pending_short_seconds_does_not_cross_session_boundary(bridge):
    """The ``pending_short_seconds`` accumulator (production-maintained)
    is the only carry source for ``virtual_pending``. The collector
    resets it whenever a normal short activity merges into a persisted
    row, so it never crosses a session boundary in production. This
    test verifies the display model's ``virtual_pending`` carry is
    sourced purely from ``pending_short_seconds`` (the legacy
    ``short_activity_carry`` JSON is gone).
    """
    from worktrace.services import settings_service
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )

    # Set pending_short_seconds to a known value.
    settings_service.set_setting("pending_short_seconds", "20")
    settings_service.clear_settings_cache()

    # No anchor exists (no DB rows today), so the snapshot is virtual_pending.
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            extra_seconds=0,
            is_persisted=False,
        )
    )

    model = build_activity_display_model()
    assert model["live_clock"]["live_state"] == "virtual_pending"
    # carry_seconds MUST equal pending_short_seconds (20).
    assert int(model["live_clock"]["carry_seconds"]) == 20, (
        "virtual_pending carry_seconds MUST come from pending_short_seconds "
        "(the production-maintained accumulator); the legacy structured "
        "short_activity_carry JSON was removed"
    )
    # duration_at_sample = snapshot_total (10) + carry (20) = 30.
    assert int(model["live_clock"]["duration_seconds_at_sample"]) == 30

    # Cleanup.
    settings_service.set_setting("pending_short_seconds", "0")
    settings_service.clear_settings_cache()
