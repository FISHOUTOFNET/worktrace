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


# --- fixtures --------------------------------------------------------------


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


# --- unified live clock single sample ---------------


def test_stable_live_key_consistent_across_overview_recent_timeline_detail(bridge):
    """Overview / Recent / Timeline / Detail must
    consume the same stable_live_key / stable_live_key_hash from the same
    snapshot. Each bridge method delegates to
    ``build_current_activity_summary`` / ``build_virtual_session`` /
    ``build_virtual_detail_row``, so the key must be identical everywhere."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    overview = bridge.get_overview()
    recent = bridge.get_recent_activities()
    timeline = bridge.get_timeline()
    details = bridge.get_timeline_session_details([], None)

    # The live_display payload (from build_current_activity_summary) must
    # carry stable_live_key / stable_live_key_hash.
    ov_ld = overview.get("live_display", {})
    rc_ld = recent.get("live_display", {})
    tl_ld = timeline.get("live_display", {})
    dt_ld = details.get("live_display", {})

    assert ov_ld["stable_live_key"]
    assert ov_ld["stable_live_key_hash"]

    # All four must share the same stable identity.
    assert ov_ld["stable_live_key"] == rc_ld["stable_live_key"]
    assert ov_ld["stable_live_key"] == tl_ld["stable_live_key"]
    assert ov_ld["stable_live_key"] == dt_ld["stable_live_key"]
    assert ov_ld["stable_live_key_hash"] == tl_ld["stable_live_key_hash"]
    assert ov_ld["stable_live_key_hash"] == dt_ld["stable_live_key_hash"]

    # Virtual session / detail items must also carry the same stable key.
    tl_virtual = timeline["sessions"][0]
    assert tl_virtual["stable_live_key"] == ov_ld["stable_live_key"]
    assert tl_virtual["stable_live_key_hash"] == ov_ld["stable_live_key_hash"]

    dt_virtual = details["activities"][0]
    assert dt_virtual["stable_live_key"] == ov_ld["stable_live_key"]
    assert dt_virtual["stable_live_key_hash"] == ov_ld["stable_live_key_hash"]


# --- virtual → persisted open keeps stable_live_key -------------------------


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


# --- get_refresh_state unified live clock fields ----


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


# --- date-scoped revision ---------------------------


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


# --- persisted open display project -----------------


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


# --- open-row project sync (real DB row tests) ------------------------------


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
    ``statistics_service._live_projection`` returns None for
    persisted_open snapshots (avoiding double count), so the only live
    contribution to the KPI is via the real DB session.
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


# --- refresh_revision is structural-only -----------


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


# --- virtual session/detail display-only -----------


def test_virtual_session_and_detail_are_display_only(bridge):
    """virtual session/detail rows must be
    display-only with ``activity_id`` 0, ``edit_disabled`` True,
    ``source`` "snapshot"."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    timeline = bridge.get_timeline()
    virtual_session = timeline["sessions"][0]
    assert virtual_session["is_virtual"] is True
    assert virtual_session["edit_disabled"] is True
    assert virtual_session["source"] == "snapshot"
    assert virtual_session["activity_ids"] == []

    details = bridge.get_timeline_session_details([], None)
    virtual_row = details["activities"][0]
    assert virtual_row["is_virtual"] is True
    assert virtual_row["edit_disabled"] is True
    assert virtual_row["activity_id"] == 0
    assert virtual_row["source"] == "snapshot"


# --- timeline service no datetime.now() fallback ----


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


# --- persisted_open contract fields ----------


def test_persisted_open_recent_item_carries_stable_live_fields(bridge):
    """persisted_open DB rows in
    ``get_recent_activities`` must carry the same stable live fields
    (``stable_live_key_hash``, ``live_started_at_epoch_ms``,
    ``carry_seconds``, ``live_state``) as virtual rows so the frontend
    continuity key survives the virtual → persisted_open transition."""
    from worktrace.services.live_display_service import (
        LIVE_ROW_CONTRACT_FIELDS,
        assert_live_row_contract,
    )

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

    # All contract fields must be present.
    assert_live_row_contract(persisted_item)


def test_persisted_open_timeline_session_carries_stable_live_fields(bridge):
    """persisted_open DB sessions in
    ``get_timeline`` must carry the same stable live fields as virtual
    sessions."""
    from worktrace.services.live_display_service import assert_live_row_contract

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
    assert_live_row_contract(persisted_session)


def test_persisted_open_detail_row_carries_stable_live_fields(bridge):
    """persisted_open DB detail rows in
    ``get_timeline_session_details`` must carry the same stable live
    fields as virtual detail rows."""
    from worktrace.services.live_display_service import assert_live_row_contract

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
    assert_live_row_contract(persisted_detail)


def test_virtual_to_persisted_open_stable_key_hash_unchived_at_bridge(bridge):
    """the stable_live_key_hash must be
    identical for the virtual row and the persisted_open DB row when
    only ``is_persisted`` / ``persisted_activity_id`` change. This is
    the bridge-level version of ``test_stable_live_key_survives_virtual_to_persisted_transition``.
    """
    aid, start_time = _create_real_open_activity(
        app_name="AppA",
        process_name="AppA.exe",
        elapsed_seconds=45,
    )
    # Virtual snapshot (unpersisted).
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=45,
            is_persisted=False,
            start_time=start_time,
        )
    )
    recent_virtual = bridge.get_recent_activities()
    virtual_item = None
    for item in recent_virtual["activities"]:
        if item.get("is_virtual_live"):
            virtual_item = item
            break
    assert virtual_item is not None
    virtual_hash = virtual_item["stable_live_key_hash"]
    assert virtual_hash

    # Persisted_open snapshot (same activity identity).
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=45,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )
    recent_persisted = bridge.get_recent_activities()
    persisted_item = None
    for item in recent_persisted["activities"]:
        if int(item.get("activity_id") or 0) == aid:
            persisted_item = item
            break
    assert persisted_item is not None
    persisted_hash = persisted_item["stable_live_key_hash"]
    assert persisted_hash

    # The stable_live_key_hash must be identical.
    assert virtual_hash == persisted_hash, (
        "stable_live_key_hash must not change across virtual → persisted_open"
    )


# --- Section 六.1: apply_persisted_open_overlay_to_row overlays ALL project fields ---


def _pending_persisted_open_snapshot(
    *,
    aid: int,
    start_time: str,
    display_name: str = "ProjectA",
    candidate_name: str = "ProjectB",
    display_is_uncategorized: bool = False,
) -> dict:
    """Build a pending persisted_open snapshot with display_project /
    candidate_project blocks.

    ``display_project`` is the inherited last-confirmed project;
    ``candidate_project`` is the new resource's inferred project. During
    the 30-second pending window the live UI must show
    ``display_project``, NOT ``candidate_project``.
    """
    display = {
        "id": 12 if not display_is_uncategorized else None,
        "name": display_name,
        "description": display_name + " description",
        "source": "inherited" if not display_is_uncategorized else "uncategorized",
        "is_uncategorized": display_is_uncategorized,
        "is_suggested_project": False,
    }
    candidate = {
        "id": 18,
        "name": candidate_name,
        "description": candidate_name + " description",
        "source": "folder_rule",
        "is_uncategorized": False,
        "is_suggested_project": False,
    }
    snap = _normal_snapshot(
        elapsed_seconds=60,
        is_persisted=True,
        persisted_activity_id=aid,
        inferred_project_name=display_name,
        start_time=start_time,
    )
    snap["display_project"] = display
    snap["candidate_project"] = candidate
    snap["project_transition"] = {
        "pending": True,
        "started_at": "",
        "elapsed_seconds": 12,
        "threshold_seconds": 30,
        "from_project_id": 12 if not display_is_uncategorized else None,
        "to_project_id": 18,
    }
    snap["project_transition_pending"] = True
    return snap


def test_apply_persisted_open_overlay_to_row_overlays_all_project_fields(bridge):
    """Section 一.3 / 六.1: ``apply_persisted_open_overlay_to_row`` must
    overlay BOTH the unified live clock fields AND the display-facing
    project fields. Matching a persisted open row must override
    ``project_id`` / ``project_name`` / ``project_description`` /
    ``display_project`` / ``candidate_project`` / ``project_transition`` /
    ``project_transition_pending`` / ``is_uncategorized`` /
    ``is_classified`` — not just the live clock fields.
    """
    from worktrace.services.live_display_service import (
        apply_persisted_open_overlay_to_row,
        build_persisted_open_overlay,
    )

    aid, start_time = _create_real_open_activity(elapsed_seconds=60)
    snapshot = _pending_persisted_open_snapshot(aid=aid, start_time=start_time)
    _set_snapshot(snapshot)
    today = timeline_service.get_default_report_date()

    overlay = build_persisted_open_overlay(snapshot, today, today)
    assert overlay is not None, "overlay must be built for a persisted_open snapshot"

    # Build a session row that matches the persisted_activity_id. The row
    # starts with DB candidate project fields that MUST be overlaid.
    session_row = {
        "activity_id": aid,
        "first_activity_id": aid,
        "activity_ids": [aid],
        "project_id": 999,
        "project_name": "DB_Candidate_Project",
        "project_description": "DB candidate desc",
        "is_uncategorized": False,
        "is_classified": True,
        "live_state": "",
        "stable_live_key": "",
        "stable_live_key_hash": "",
        "live_display_key": "",
        "live_started_at_epoch_ms": 0,
        "carry_seconds": 0,
        "is_virtual_live": False,
        "is_in_progress": False,
        "is_live_projected": False,
        "edit_disabled": False,
        "disable_reason": "",
        "source": "db",
        "display_project": None,
        "candidate_project": None,
        "project_transition": None,
        "project_transition_pending": False,
        "status": "",
        "start_time": "",
    }
    apply_persisted_open_overlay_to_row(session_row, overlay)

    # Unified live clock fields must be overlaid.
    assert session_row["live_state"] == "persisted_open"
    assert session_row["stable_live_key_hash"]
    assert session_row["live_started_at_epoch_ms"] > 0
    # Display-facing project fields must be overlaid from display_project.
    assert session_row["project_name"] == "ProjectA"
    assert session_row["project_description"] == "ProjectA description"
    assert session_row["display_project"]["name"] == "ProjectA"
    assert session_row["candidate_project"]["name"] == "ProjectB"
    assert session_row["project_transition_pending"] is True
    assert session_row["is_uncategorized"] is False
    assert session_row["is_classified"] is True
    # Edit controls must be disabled for in-progress rows.
    assert session_row["edit_disabled"] is True
    assert session_row["disable_reason"]


def test_apply_persisted_open_overlay_to_row_candidate_does_not_override_project_name(bridge):
    """Section 一.5 / 六.1: ``candidate_project`` must NEVER override
    ``project_name`` / ``project_description`` / ``project_id``. Even
    when the candidate is a concrete project and the display is
    uncategorized, the overlay keeps ``project_name`` aligned with
    ``display_project.name``.
    """
    from worktrace.services.live_display_service import (
        apply_persisted_open_overlay_to_row,
        build_persisted_open_overlay,
    )

    aid, start_time = _create_real_open_activity(elapsed_seconds=60)
    snapshot = _pending_persisted_open_snapshot(
        aid=aid,
        start_time=start_time,
        display_name=UNCATEGORIZED_PROJECT,
        candidate_name="ProjectB",
        display_is_uncategorized=True,
    )
    _set_snapshot(snapshot)
    today = timeline_service.get_default_report_date()

    overlay = build_persisted_open_overlay(snapshot, today, today)
    session_row = {
        "activity_id": aid,
        "first_activity_id": aid,
        "activity_ids": [aid],
        "project_id": 999,
        "project_name": "DB_Candidate",
        "project_description": "",
        "is_uncategorized": False,
        "is_classified": True,
        "live_state": "",
        "stable_live_key": "",
        "stable_live_key_hash": "",
        "live_display_key": "",
        "live_started_at_epoch_ms": 0,
        "carry_seconds": 0,
        "is_virtual_live": False,
        "is_in_progress": False,
        "is_live_projected": False,
        "edit_disabled": False,
        "disable_reason": "",
        "source": "db",
        "display_project": None,
        "candidate_project": None,
        "project_transition": None,
        "project_transition_pending": False,
        "status": "",
        "start_time": "",
    }
    apply_persisted_open_overlay_to_row(session_row, overlay)

    # project_name follows display_project (uncategorized), NOT candidate.
    assert session_row["project_name"] == UNCATEGORIZED_PROJECT
    assert session_row["is_uncategorized"] is True
    assert session_row["is_classified"] is False
    # candidate_project is exposed as a separate field only.
    assert session_row["candidate_project"]["name"] == "ProjectB"
    # project_id follows display_project.id (None -> 0), NOT candidate.id.
    assert session_row["project_id"] == 0


def test_apply_persisted_open_overlay_to_row_does_not_overlay_non_matching_row(bridge):
    """``apply_persisted_open_overlay_to_row`` must NOT
    overlay a row whose ``activity_id`` / ``first_activity_id`` /
    ``activity_ids`` do NOT contain the persisted_activity_id. Closed
    historical rows must remain untouched.
    """
    from worktrace.services.live_display_service import (
        apply_persisted_open_overlay_to_row,
        build_persisted_open_overlay,
    )

    aid, start_time = _create_real_open_activity(elapsed_seconds=60)
    snapshot = _pending_persisted_open_snapshot(aid=aid, start_time=start_time)
    _set_snapshot(snapshot)
    today = timeline_service.get_default_report_date()

    overlay = build_persisted_open_overlay(snapshot, today, today)
    # A closed historical row with a different activity_id.
    closed_row = {
        "activity_id": 8888,
        "first_activity_id": 8888,
        "activity_ids": [8888],
        "project_id": 555,
        "project_name": "ClosedProject",
        "project_description": "closed desc",
        "live_state": "",
        "stable_live_key_hash": "",
        "edit_disabled": False,
        "source": "db",
    }
    apply_persisted_open_overlay_to_row(closed_row, overlay)
    # The closed row is NOT overlaid.
    assert closed_row["project_name"] == "ClosedProject"
    assert closed_row["live_state"] == ""
    assert closed_row["edit_disabled"] is False
