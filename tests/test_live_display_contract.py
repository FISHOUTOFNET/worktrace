"""Unified live-display contract tests (verification items 1-13).

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


# --- Verification item 1: unified live clock single sample ---------------


def test_stable_live_key_consistent_across_overview_recent_timeline_detail(bridge):
    """Verification item 1: Overview / Recent / Timeline / Detail must
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


# --- Verification item 3: virtual → persisted open keeps stable_live_key


def test_stable_live_key_survives_virtual_to_persisted_transition(bridge):
    """Verification item 3/16: the same activity transitioning from virtual
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
    """Verification item 3: when the start_time changes (a genuinely
    different activity), the stable_live_key must also change."""
    s1 = _normal_snapshot(elapsed_seconds=10, start_time="2026-07-01 10:00:00")
    s2 = _normal_snapshot(elapsed_seconds=20, start_time="2026-07-01 11:00:00")
    assert _stable_live_key(s1) != _stable_live_key(s2)


# --- Verification item 4: get_refresh_state unified live clock fields ----


def test_get_refresh_state_returns_unified_live_clock_fields(bridge):
    """Verification item 4/6: ``get_refresh_state`` must return the unified
    live clock fields so the frontend ticker can use scheme A
    (``carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)``)
    instead of a response-time baseline."""
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


# --- Verification item 8: date-scoped revision ---------------------------


def test_get_refresh_state_accepts_report_date(bridge):
    """Verification item 8: ``get_refresh_state`` must accept an optional
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
    """Verification item 8: the bridge method signature must accept
    ``report_date`` and pass it through to the API."""
    # The bridge method must accept the parameter without error.
    result = bridge.get_refresh_state(report_date="2026-06-15")
    assert result["ok"] is True
    assert result["report_date"] == "2026-06-15"


# --- Verification item 5: persisted open display project -----------------


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
    """Verification item 5 (defensive fallback path): when a real
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


# --- Verification item 5b: open-row project sync (real DB row tests) -----


def test_persisted_open_display_project_does_not_revert_with_real_uncategorized_row(bridge):
    """Verification item 5b: a real persisted open DB row that starts
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
    """Verification items 5b / acceptance 2-5: after the open-row sync
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


# --- Verification item 7: refresh_revision is structural-only -----------


def test_persisted_open_natural_duration_does_not_change_revision(bridge):
    """Verification item 7: a persisted open row's natural duration
    growth (via ``set_activity_duration``) must NOT change
    ``refresh_revision``. The revision excludes ``duration_seconds`` and
    ``updated_at`` from the per-row structural signature."""
    from worktrace.services import activity_service

    # Insert a closed activity so the revision has a baseline.
    aid = activity_service.create_activity(
        "App", "App.exe", "Spec", start_time="2026-07-01 09:00:00"
    )
    activity_service.close_activity(aid, "2026-07-01 09:30:00")
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
    """Verification item 6: a manual project assignment change must change
    ``refresh_revision``."""
    from worktrace.services import activity_service, project_service

    aid = activity_service.create_activity(
        "App", "App.exe", "Spec", start_time="2026-07-01 09:00:00"
    )
    activity_service.close_activity(aid, "2026-07-01 09:30:00")
    r1 = bridge.get_refresh_state()["refresh_revision"]

    # Assign a project — a structural change.
    pid = project_service.create_project("MyProject")
    activity_service.update_activity_project(aid, pid)
    r2 = bridge.get_refresh_state()["refresh_revision"]
    assert r1 != r2, (
        "refresh_revision must change when project assignment is added"
    )


def test_time_edit_changes_revision(bridge):
    """Verification item 6: a time edit (changing start_time / end_time)
    must change ``refresh_revision``."""
    from worktrace.services import activity_service

    aid = activity_service.create_activity(
        "App", "App.exe", "Spec", start_time="2026-07-01 09:00:00"
    )
    activity_service.close_activity(aid, "2026-07-01 09:30:00")
    r1 = bridge.get_refresh_state()["refresh_revision"]

    # Edit the time — a structural change.
    activity_service.update_activity_time(aid, "2026-07-01 09:05:00", "2026-07-01 09:30:00")
    r2 = bridge.get_refresh_state()["refresh_revision"]
    assert r1 != r2


# --- Verification item 11: virtual session/detail display-only -----------


def test_virtual_session_and_detail_are_display_only(bridge):
    """Verification item 11: virtual session/detail rows must be
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


# --- Verification item 12: timeline service no datetime.now() fallback ----


def test_timeline_service_no_datetime_now_fallback():
    """Verification item 12: ``timeline_service._display_duration`` must
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
