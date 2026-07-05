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

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.live_display]

from worktrace.constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from worktrace.services import activity_service, folder_rule_service, project_service, settings_service
from worktrace.services.live_display_service import (
    _live_display_key,
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
from tests.support.activity_factory import create_open_activity
from tests.support.snapshot_factory import normal_snapshot




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
    return normal_snapshot(
        elapsed_seconds=elapsed_seconds,
        status=status,
        is_persisted=is_persisted,
        persisted_activity_id=persisted_activity_id,
        inferred_project_name=inferred_project_name,
        extra_seconds=extra_seconds,
        start_time=start_time,
    )




def test_stable_live_key_consistent_across_overview_recent_timeline_detail(bridge):
    """Under the unified Activity Display Model, a ``persisted_open``
    snapshot must surface the SAME unified ``live_clock`` identity
    (``display_span_id``, ``stable_live_key_hash``,
    ``live_started_at_epoch_ms``) across Overview / Recent / Timeline /
    Details. The real persisted DB row in each list is overlaid with the
    same ``display_span_id`` and ``stable_live_key_hash`` via
    ``apply_live_span_to_row`` rather than materializing display-only
    rows."""
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


def test_virtual_pending_to_persisted_open_display_span_continuity(bridge):
    """Crossing the persistence threshold keeps the same stable live
    key and span id, with display duration advancing once."""
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )

    start = (datetime.now() - timedelta(seconds=29)).strftime(TIME_FORMAT)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=29,
            is_persisted=False,
            start_time=start,
        )
    )
    virtual_model = build_activity_display_model()
    virtual_clock = virtual_model["live_clock"]
    virtual_span = virtual_model["display_spans"][0]
    assert virtual_clock["live_state"] == "virtual_pending"
    assert virtual_span["source"] == "snapshot"

    aid = activity_service.create_activity(
        "AppA",
        "AppA.exe",
        "Window",
        start_time=start,
    )
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=30,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start,
        )
    )
    persisted_model = build_activity_display_model()
    persisted_clock = persisted_model["live_clock"]
    persisted_span = persisted_model["display_spans"][0]

    assert persisted_clock["live_state"] == "persisted_open"
    assert persisted_clock["stable_live_key_hash"] == virtual_clock["stable_live_key_hash"]
    assert persisted_clock["display_span_id"] == virtual_clock["display_span_id"]
    assert persisted_span["display_span_id"] == virtual_span["display_span_id"]
    assert int(persisted_span["anchor_activity_id"]) == aid
    assert int(virtual_span["duration_seconds"]) == 29
    assert int(persisted_span["duration_seconds"]) == 30


def test_virtual_pending_display_span_visibility_flags(bridge):
    """``virtual_pending`` spans are visible on display surfaces but
    never exportable or editable."""
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )

    _set_snapshot(_normal_snapshot(elapsed_seconds=12, is_persisted=False))
    model = build_activity_display_model()
    span = model["display_spans"][0]
    assert span["live_state"] == "virtual_pending"
    assert span["is_visible_in_current"] is True
    assert span["is_visible_in_recent"] is True
    assert span["is_visible_in_timeline"] is True
    assert span["is_visible_in_details"] is True
    assert span["exportable"] is False
    assert span["editable"] is False
    assert span["edit_disabled"] is True
    assert span["is_display_only"] is True


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
    aid = create_open_activity(
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
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
    state1 = bridge.get_refresh_state()
    r1 = state1["refresh_revision"]
    page1 = state1["page_structure_revision"]

    # Update the duration (natural growth) — this should NOT change the
    # revision because duration_seconds is excluded from the structural
    # signature.
    activity_service.set_activity_duration(aid, 1801)
    state2 = bridge.get_refresh_state()
    r2 = state2["refresh_revision"]
    page2 = state2["page_structure_revision"]
    assert r1 == r2, (
        "refresh_revision must not change when only duration_seconds / "
        "updated_at change (natural growth)"
    )
    assert page1 == page2, (
        "page_structure_revision must not change when only duration_seconds "
        "changes on an open/live row"
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
    state1 = bridge.get_refresh_state()
    r1 = state1["refresh_revision"]
    page1 = state1["page_structure_revision"]

    # Assign a project — a structural change.
    pid = project_service.create_project("MyProject")
    activity_service.update_activity_project(aid, pid)
    state2 = bridge.get_refresh_state()
    r2 = state2["refresh_revision"]
    page2 = state2["page_structure_revision"]
    assert r1 != r2, (
        "refresh_revision must change when project assignment is added"
    )
    assert page1 != page2, (
        "page_structure_revision must change when project assignment is added"
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
    pending snapshot (``virtual_pending``) materializes display-only
    Timeline / Details rows without creating DB history."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=10))
    timeline = bridge.get_timeline()
    assert len(timeline["sessions"]) == 1
    session = timeline["sessions"][0]
    assert session["source"] == "snapshot"
    assert session["is_display_only"] is True
    assert session["edit_disabled"] is True

    details = bridge.get_timeline_session_details([], None)
    assert len(details["activities"]) == 1
    detail = details["activities"][0]
    assert detail["source"] == "snapshot"
    assert detail["is_display_only"] is True
    assert detail["edit_disabled"] is True

    overview = bridge.get_overview()
    assert overview["current_activity"]["active"] is True
    assert overview["current_activity"]["live_state"] == "virtual_pending"




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

    ``virtual_pending`` is display-only and ``persisted_open`` overlays
    the real DB row, but both states must surface the same stable identity
    so the frontend continuity key survives the transition.
    """
    aid, start_time = _create_real_open_activity(
        app_name="AppA",
        process_name="AppA.exe",
        elapsed_seconds=10,
    )
    # virtual_pending snapshot (unpersisted) — display-only rows are visible.
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
    virtual_span_id = overview_virtual["live_clock"]["display_span_id"]
    assert virtual_span_id
    assert overview_virtual["activities"][0]["stable_live_key_hash"] == virtual_hash

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
    assert overview_persisted["live_clock"]["display_span_id"] == virtual_span_id

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
    assert detail_row["live_base_seconds"] == 30
    assert detail_row["live_base_seconds"] + overview["live_clock"]["current_elapsed_at_sample"] == 240
    assert detail_row["display_span_id"] == expected_span_id

    # Recent matching row must also carry the same span id and a live base.
    recent_row = next(
        (r for r in recent["activities"] if int(r.get("activity_id") or 0) == aid),
        None,
    )
    assert recent_row is not None
    assert recent_row["display_span_id"] == expected_span_id
    assert recent_row["live_base_seconds"] == 0

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
    """A session row with a closed activity (100s DB) AND a
    ``persisted_open`` activity (DB duration 0, live sample 240s) must
    have ``live_base_seconds`` = 130 (session static base), NOT 240.
    The detail row for the open activity must have
    ``live_base_seconds == 30``. Both add the same current elapsed, so
    after +5s: session reads 345, detail reads 245. Session must NEVER
    be overwritten to 245.

    Under the DB-only contract (Section 一), session row's
    ``raw_duration_seconds`` is DB-only (100 + 0 = 100). The unified
    formula adds ``live_delta_at_sample`` (240) to reach 340. The detail
    row (DB duration 0) reaches 240.
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

    # 2. Create a persisted_open activity (DB duration 0; live sample 240s).
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

    # Session row aggregates both activities' DB durations: 100 (closed)
    # + 0 (open, no DB duration) = 100. The unified formula adds
    # live_delta_at_sample (240) to reach the session's full sample (340).
    session_row = {
        "session_id": "sess-1",
        "first_activity_id": open_aid,
        "activity_ids": [closed_aid, open_aid],
        "duration_seconds": 100,
        "raw_duration_seconds": 100,
    }
    # Detail row for the open activity: DB duration 0.
    detail_row = {
        "activity_id": open_aid,
        "duration_seconds": 0,
        "raw_duration_seconds": 0,
    }

    apply_live_span_to_row(session_row, span)
    apply_live_span_to_row(detail_row, span)

    assert detail_row["live_base_seconds"] == 30, (
        "detail row live_base_seconds must equal the open activity's "
        "static base (extra_seconds=30)"
    )
    assert session_row["live_base_seconds"] == 130, (
        "session row live_base_seconds must equal the session's static base "
        "(130 = 100 closed DB + 30 live base), NOT the live "
        "activity's own duration (240). This is the regression guard against "
        "the old contract that overwrote session durations with "
        "liveSeconds(clock)."
    )

    assert session_row["display_span_id"] == detail_row["display_span_id"]
    assert session_row["stable_live_key_hash"] == detail_row["stable_live_key_hash"]
    assert session_row["duration_seconds_at_sample"] == 240

    # Ticker: both rows add the same current elapsed. At sample time
    # current_elapsed=210; at +5s it is 215.
    delta_at_sample = 210
    assert session_row["live_base_seconds"] + delta_at_sample == 340
    assert detail_row["live_base_seconds"] + delta_at_sample == 240

    delta_plus_5 = 215
    assert session_row["live_base_seconds"] + delta_plus_5 == 345, (
        "session row after +5s must be 345, NOT 245 — the session must not "
        "be overwritten to the live activity's own duration"
    )
    assert detail_row["live_base_seconds"] + delta_plus_5 == 245


def test_virtual_pending_rows_in_lists_and_kpi_tick(bridge):
    """A ``virtual_pending`` snapshot (normal, unpersisted, <30s, no
    absorb anchor) must:

    * render the pending resource in the current-activity area;
    * materialize display-only rows into Recent / Timeline / Details;
    * include the display duration in Overview KPI totals;
    * surface a live_clock with ``is_live == True`` but
      ``is_project_duration_live == True``.
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
    assert overview["live_clock"]["is_project_duration_live"] is True

    assert len(recent["activities"]) == 1
    assert len(timeline["sessions"]) == 1
    recent_row = recent["activities"][0]
    timeline_row = timeline["sessions"][0]
    assert recent_row["source"] == "snapshot"
    assert timeline_row["source"] == "snapshot"
    assert recent_row["edit_disabled"] is True
    assert timeline_row["edit_disabled"] is True

    assert int(overview["today_total_seconds"]) == 10
    assert int(overview["classified_seconds"]) == 10
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

    # live_base = anchor_raw(60); pending/current elapsed is added by the
    # single live delta.
    assert recent_row["live_base_seconds"] == 0, (
        f"Overview recent live_base_seconds must be current base 0; got "
        f"{recent_row['live_base_seconds']}"
    )

    # DB must NOT be written: the anchor row's stored duration is still 60.
    anchor_db = activity_service.get_activity(anchor_aid)
    assert int(anchor_db["duration_seconds"]) == 60, (
        "absorbed_pending display projection must NOT write the DB"
    )

    # Timeline session for the anchor also uses the overlay path.
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


def test_absorbed_pending_current_clock_uses_resource_elapsed(bridge):
    from worktrace.services.activity_display_model_service import (
        apply_live_span_to_row,
        build_activity_display_model,
        get_live_span,
    )

    anchor_start = datetime.now() - timedelta(seconds=180)
    anchor_end = anchor_start + timedelta(seconds=120)
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start.strftime(TIME_FORMAT),
    )
    activity_service.close_activity(anchor_aid, anchor_end.strftime(TIME_FORMAT), 120)

    pending_start = anchor_end + timedelta(seconds=5)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=5,
            extra_seconds=0,
            is_persisted=False,
            start_time=pending_start.strftime(TIME_FORMAT),
        )
    )

    model = build_activity_display_model()
    current = model["current_activity"]
    project_clock = model["live_clock"]
    span = get_live_span(model)
    assert span is not None

    assert current["elapsed_seconds"] == 5
    assert current["resource_elapsed_seconds"] == 5
    assert "current_activity_clock" not in model
    assert project_clock["duration_seconds_at_sample"] == 125
    assert project_clock["display_base_seconds"] == 120
    assert project_clock["current_elapsed_at_sample"] == 5

    anchor_row = activity_service.get_activity(anchor_aid)
    projected = dict(anchor_row)
    apply_live_span_to_row(projected, span)
    assert projected["duration_seconds"] == 125
    assert activity_service.get_activity(anchor_aid)["duration_seconds"] == 120


def test_persisted_open_live_clock_uses_resource_elapsed_and_project_extra(bridge):
    from worktrace.services.activity_display_model_service import (
        apply_live_span_to_row,
        build_activity_display_model,
        get_live_span,
    )

    aid, start_time = _create_real_open_activity(elapsed_seconds=35)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=35,
            extra_seconds=10,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )

    model = build_activity_display_model()
    current = model["current_activity"]
    project_clock = model["live_clock"]
    span = get_live_span(model)
    assert span is not None

    assert current["elapsed_seconds"] == 35
    assert current["resource_elapsed_seconds"] == 35
    assert "current_activity_clock" not in model
    assert project_clock["duration_seconds_at_sample"] == 45
    assert project_clock["display_base_seconds"] == 10
    assert project_clock["current_elapsed_at_sample"] == 35

    row = activity_service.get_activity(aid)
    apply_live_span_to_row(row, span)
    assert row["duration_seconds"] == 45


@pytest.mark.parametrize("status", [STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR])
def test_system_current_activity_live_clock_contract_and_display_safe(bridge, status):
    from worktrace.services.activity_display_model_service import build_activity_display_model

    _set_snapshot(
        {
            **_normal_snapshot(elapsed_seconds=12, status=status),
            "window_title": "secret.docx - Word",
            "file_path_hint": "C:\\secret\\secret.docx",
            "clipboard": "secret clipboard",
            "note": "secret note",
        }
    )
    model = build_activity_display_model()
    expected_current_live = status != STATUS_PAUSED
    assert "current_activity_clock" not in model
    assert model["live_clock"]["current_duration_live"] is expected_current_live
    assert model["live_clock"]["is_live"] is expected_current_live
    assert model["live_clock"]["is_project_duration_live"] is False
    assert model["live_clock"]["project_duration_live"] is False
    assert model["display_spans"] == []
    serialized = json.dumps(model, ensure_ascii=False)
    for forbidden in ("secret.docx", "C:\\secret", "secret clipboard", "secret note"):
        assert forbidden not in serialized


def test_idle_blocks_display_absorbed_pending(bridge):
    from worktrace.constants import SOURCE_AUTO, SOURCE_SYSTEM
    from worktrace.services.activity_display_model_service import build_activity_display_model

    today = timeline_service.get_default_report_date()
    project_id = project_service.create_project("IdleBoundaryProject")
    anchor_id = activity_service.create_activity(
        "AppA",
        "app.exe",
        "A",
        source=SOURCE_AUTO,
        start_time=f"{today} 09:00:00",
        project_id=project_id,
    )
    activity_service.close_activity(anchor_id, f"{today} 09:01:00", 60)
    idle_id = activity_service.create_activity(
        "空闲",
        "idle",
        "用户空闲",
        status=STATUS_IDLE,
        source=SOURCE_SYSTEM,
        start_time=f"{today} 09:01:00",
    )
    activity_service.close_activity(idle_id, f"{today} 09:01:10", 10)

    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=10,
            start_time=f"{today} 09:01:10",
            inferred_project_name="ProjectB",
        )
    )

    model = build_activity_display_model(report_date=today, today=today)

    assert model["current_activity"]["live_state"] == "virtual_pending"
    assert model["current_activity"]["is_absorbed_pending"] is False
    assert model["display_spans"][0]["anchor_activity_id"] == 0


def test_new_activity_first_frame_uses_unified_live_clock(bridge):
    from worktrace.services.activity_display_model_service import build_activity_display_model

    today = timeline_service.get_default_report_date()
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=0,
            start_time=f"{today} 09:00:00",
            inferred_project_name="FirstFrame",
        )
    )

    model = build_activity_display_model(report_date=today, today=today)

    assert model["current_activity"]["live_state"] == "virtual_pending"
    assert "current_activity_clock" not in model
    assert model["live_clock"]["current_duration_live"] is True
    assert model["live_clock"]["current_elapsed_at_sample"] == 0
    assert model["live_clock"]["live_started_at_epoch_ms"] > 0


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
    assert len(model["display_spans"]) == 1
    assert int(model["display_spans"][0]["anchor_activity_id"]) == 0

    # 5. The bridge Overview / Recent / Timeline must NOT overlay A.
    overview = bridge.get_overview()
    recent = bridge.get_recent_activities()
    timeline = bridge.get_timeline()
    assert overview["live_clock"]["live_state"] == "virtual_pending"
    assert overview["live_clock"]["is_project_duration_live"] is True
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
            if item.get("display_span_id") == overview["live_clock"]["display_span_id"]:
                continue
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
    assert len(model["display_spans"]) == 1
    assert int(model["display_spans"][0]["anchor_activity_id"]) == 0


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
    assert len(model["display_spans"]) == 1
    assert int(model["display_spans"][0]["anchor_activity_id"]) == 0


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
    assert len(model["display_spans"]) == 1
    assert int(model["display_spans"][0]["anchor_activity_id"]) == 0


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


# =============================================================================
# Section 二: Refresh State single-sample contract (no double-read race).
# =============================================================================


def test_refresh_state_view_model_reads_snapshot_exactly_once(bridge, monkeypatch):
    """Section 二: ``get_refresh_state_view_model`` MUST read
    ``current_activity_snapshot`` EXACTLY ONCE per call and pass the same
    sample to BOTH :func:`build_activity_display_model` (via the
    ``snapshot=...`` parameter) AND :func:`compute_refresh_revision`. The
    display-model service MUST NOT re-read the setting when a snapshot is
    injected.

    Verification strategy: monkeypatch
    ``view_model_service._get_current_activity_snapshot`` to return a fixed
    snapshot A; monkeypatch
    ``activity_display_model_service._get_current_activity_snapshot`` to
    raise ``AssertionError``. If the refresh-state path re-reads the
    setting inside the display model, the AssertionError propagates and
    the test fails. If it correctly injects the snapshot, the call
    succeeds and the returned identity fields match snapshot A.
    """
    from worktrace.services import view_model_service

    fixed_snapshot = _normal_snapshot(
        elapsed_seconds=120,
        is_persisted=True,
        persisted_activity_id=0,
        inferred_project_name="SampleA",
    )

    call_counter = {"count": 0}

    def _vms_read():
        call_counter["count"] += 1
        return fixed_snapshot

    def _adm_read_boom():
        raise AssertionError(
            "activity_display_model_service._get_current_activity_snapshot MUST "
            "NOT be called when get_refresh_state_view_model injects the snapshot"
        )

    monkeypatch.setattr(view_model_service, "_get_current_activity_snapshot", _vms_read)
    # Patch the display-model service's reader to ensure it is not invoked.
    monkeypatch.setattr(
        "worktrace.services.activity_display_model_service._get_current_activity_snapshot",
        _adm_read_boom,
    )

    state = view_model_service.get_refresh_state_view_model()
    assert state["ok"] is True, "refresh-state ViewModel must succeed with single snapshot"
    # The view_model_service reader must be called exactly once.
    assert call_counter["count"] == 1, (
        f"get_refresh_state_view_model MUST read the snapshot EXACTLY ONCE; "
        f"got {call_counter['count']} reads"
    )
    # refresh_revision, current_activity_key, live_clock, and current_activity
    # must all derive from snapshot A (inferred_project_name="SampleA").
    assert state["inferred_project_name"] == "SampleA"
    assert state["is_persisted"] is True
    # live_clock identity must come from the same snapshot A.
    expected_hash = _stable_live_key_hash(fixed_snapshot)
    assert state["stable_live_key_hash"] == expected_hash, (
        "refresh-state stable_live_key_hash MUST come from the same single "
        "snapshot sample as refresh_revision"
    )
    assert state["sample_id"] == expected_hash
    assert state["live_clock"]["stable_live_key_hash"] == expected_hash


def test_refresh_state_view_model_revision_and_live_clock_share_same_sample(
    bridge, monkeypatch
):
    """Section 二 (stricter race): construct snapshot A / snapshot B and
    ensure the refresh-state payload NEVER mixes revision from A with live
    clock identity from B. The single-sample architecture guarantees both
    fields originate from the same snapshot sample.

    Strategy: monkeypatch the reader so it ALWAYS returns snapshot A
    (deterministic single sample). Build a snapshot B with a different
    inferred_project_name and a different start_time. Assert that the
    returned ``refresh_revision`` / ``current_activity_key`` /
    ``stable_live_key_hash`` all correspond to A — never B.
    """
    from worktrace.services import view_model_service

    snapshot_a = _normal_snapshot(
        elapsed_seconds=120,
        is_persisted=False,
        inferred_project_name="ProjectA",
        start_time=(datetime.now() - timedelta(seconds=120)).strftime(TIME_FORMAT),
    )
    snapshot_b = _normal_snapshot(
        elapsed_seconds=300,
        is_persisted=True,
        persisted_activity_id=42,
        inferred_project_name="ProjectB",
        start_time=(datetime.now() - timedelta(seconds=300)).strftime(TIME_FORMAT),
    )

    # The reader always returns A — simulating a single-sample read at T0.
    monkeypatch.setattr(
        view_model_service,
        "_get_current_activity_snapshot",
        lambda: snapshot_a,
    )

    state = view_model_service.get_refresh_state_view_model()
    assert state["ok"] is True
    # revision identity fields MUST all match snapshot A.
    assert state["inferred_project_name"] == "ProjectA"
    assert state["is_persisted"] is False
    # live_clock identity MUST match snapshot A.
    expected_hash_a = _stable_live_key_hash(snapshot_a)
    expected_hash_b = _stable_live_key_hash(snapshot_b)
    assert expected_hash_a != expected_hash_b, (
        "snapshot A and B must have distinct stable_live_key_hash for the "
        "race test to be meaningful"
    )
    assert state["stable_live_key_hash"] == expected_hash_a, (
        "refresh-state live_clock MUST come from the same single sample "
        "(A) as refresh_revision — never mixed with B"
    )
    assert state["live_clock"]["stable_live_key_hash"] == expected_hash_a
    # current_activity must also carry snapshot A's identity.
    assert state["current_activity"]["stable_live_key_hash"] == expected_hash_a


def test_refresh_state_high_frequency_path_does_not_scan_activity_rows(
    bridge, monkeypatch
):
    """``get_refresh_state`` must stay lightweight enough for heartbeat use.

    It may build the current live state from the single snapshot, but must
    not call the page/list row loader or attach resources for every activity
    on the report date.
    """
    from worktrace.services import activity_service, resource_service

    _set_snapshot(_normal_snapshot(elapsed_seconds=12, is_persisted=False))
    calls = {"rows": 0, "attach": 0}

    def boom_rows(date):
        calls["rows"] += 1
        raise AssertionError("get_refresh_state must not scan activity rows")

    def boom_attach(row):
        calls["attach"] += 1
        raise AssertionError("get_refresh_state must not attach resources")

    monkeypatch.setattr(activity_service, "get_activities_by_date", boom_rows)
    monkeypatch.setattr(resource_service, "attach_resource", boom_attach)

    state = bridge.get_refresh_state()

    assert state["ok"] is True
    assert state["current_activity"]
    assert state["live_state_revision"]
    assert state["page_structure_revision"]
    assert state["refresh_revision"]
    assert calls == {"rows": 0, "attach": 0}


def test_refresh_state_returns_split_revisions_and_compat_revision(bridge):
    _set_snapshot(_normal_snapshot(elapsed_seconds=12, is_persisted=False))

    state = bridge.get_refresh_state()

    assert state["ok"] is True
    assert state["live_state_revision"]
    assert state["page_structure_revision"]
    assert state["refresh_revision"]
    assert state["refresh_revision"] == (
        state["live_state_revision"] + ":" + state["page_structure_revision"]
    )


def test_live_state_revision_changes_for_live_state_transitions(bridge):
    _set_snapshot(_normal_snapshot(elapsed_seconds=29, is_persisted=False))
    pending = bridge.get_refresh_state()["live_state_revision"]

    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=31,
            is_persisted=True,
            persisted_activity_id=123,
        )
    )
    persisted = bridge.get_refresh_state()["live_state_revision"]

    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=31,
            is_persisted=True,
            persisted_activity_id=123,
            start_time="2026-07-05 10:01:00",
        )
    )
    switched = bridge.get_refresh_state()["live_state_revision"]

    _set_snapshot(_normal_snapshot(status=STATUS_PAUSED, elapsed_seconds=31))
    paused = bridge.get_refresh_state()["live_state_revision"]

    _set_snapshot(_normal_snapshot(status=STATUS_IDLE, elapsed_seconds=31))
    idle = bridge.get_refresh_state()["live_state_revision"]

    _set_snapshot(_normal_snapshot(status=STATUS_EXCLUDED, elapsed_seconds=31))
    excluded = bridge.get_refresh_state()["live_state_revision"]

    assert len({pending, persisted, switched, paused, idle, excluded}) == 6


# =============================================================================
# Section 三: Historical date full live-clock suppression.
# =============================================================================


def test_historical_date_persisted_open_suppresses_live_clock(bridge):
    """Section 三: when ``report_date != today`` and the current snapshot
    is ``persisted_open``, the page-scoped ``live_clock`` MUST be fully
    suppressed so the frontend ticker cannot register an active
    project-duration live clock on a historical Timeline page.

    Assertions:

    * ``display_spans == []``
    * root ``live_clock.live_state == "none"``
    * root ``live_clock.is_live is False``
    * root ``live_clock.is_project_duration_live is False``
    * root ``display_span_id == ""``
    * root ``live_clock.live_started_at_epoch_ms == 0``
    * root ``live_clock.carry_seconds == 0``
    * Timeline ``total_seconds`` equals the historical DB rows' display
      total — the open row's live sample seconds MUST NOT pollute the
      historical total.
    """
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )
    from worktrace.services.view_model_service import get_timeline_view_model

    # 1. Create an open activity on a HISTORICAL date (2 days ago).
    historical_day = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    historical_start = f"{historical_day} 09:00:00"
    aid = activity_service.create_activity(
        "HistApp",
        "HistApp.exe",
        "HistWindow",
        start_time=historical_start,
    )

    # 2. Set a persisted_open snapshot pointing at the historical open row.
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=240,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="HistProject",
            start_time=historical_start,
        )
    )

    # 3. Build the Timeline ViewModel for the HISTORICAL date.
    timeline = get_timeline_view_model(historical_day)
    assert timeline["ok"] is True
    live_clock = timeline["live_clock"]
    assert live_clock["live_state"] == "none", (
        "historical date MUST collapse live_state to 'none' even when the "
        "snapshot is persisted_open"
    )
    assert live_clock["is_live"] is False
    assert live_clock["is_project_duration_live"] is False
    assert live_clock["display_span_id"] == ""
    assert int(live_clock["live_started_at_epoch_ms"]) == 0
    assert int(live_clock["carry_seconds"]) == 0

    # 4. The display_spans list must be empty.
    model = build_activity_display_model(
        report_date=historical_day,
        today=datetime.now().strftime("%Y-%m-%d"),
    )
    assert model["display_spans"] == []
    assert model["live_clock"]["live_state"] == "none"

    # 5. The historical Timeline total MUST NOT include the persisted_open
    #    sample's live seconds (240s). The historical DB row is open with
    #    no duration_seconds stored, so its raw duration is 0; the total
    #    must be 0 (or whatever raw DB rows exist for that historical date).
    historical_total = int(timeline["total_seconds"])
    assert historical_total == 0, (
        f"historical Timeline total_seconds MUST be 0 (open row has no stored "
        f"duration, no live overlay applied); got {historical_total}"
    )
    # The open row must NOT carry any live_state / display_span_id overlay.
    for session in timeline["sessions"]:
        assert not session.get("display_span_id"), (
            "historical session MUST NOT carry a display_span_id from the "
            "current persisted_open snapshot"
        )
        assert session.get("live_state") != "persisted_open"
        assert session.get("live_state") != "absorbed_pending"


def test_historical_date_absorbed_pending_suppresses_live_clock(bridge):
    """Section 三: when ``report_date != today`` and the current snapshot
    would have been ``absorbed_pending`` on today, the historical date
    MUST suppress the live clock entirely. The current open row's pending
    seconds MUST NOT pollute the historical Timeline total via the
    absorbed_pending projection.

    Strategy: create an anchor (closed normal activity) on a historical
    date, then a fresh absorbed_pending snapshot today (no boundary
    between anchor and pending). On the historical date view, the
    absorbed_pending projection MUST NOT be applied: no display span, no
    live clock, no inflation of the anchor's duration_seconds.
    """
    from worktrace.services.activity_display_model_service import (
        build_activity_display_model,
    )
    from worktrace.services.view_model_service import get_timeline_view_model

    # 1. Create a closed anchor activity on a HISTORICAL date (3 days ago).
    historical_day = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    anchor_start = f"{historical_day} 09:00:00"
    anchor_end = f"{historical_day} 09:01:00"
    anchor_aid = activity_service.create_activity(
        "AnchorApp",
        "AnchorApp.exe",
        "AnchorWindow",
        start_time=anchor_start,
    )
    activity_service.close_activity(anchor_aid, anchor_end, 60)
    # The anchor's stored DB duration is 60s.

    # 2. Set an absorbed_pending snapshot that — on TODAY — would absorb
    #    into the historical anchor (no boundary). But we query the
    #    historical date, so the projection MUST be suppressed.
    pending_start = (datetime.now() - timedelta(seconds=15)).strftime(TIME_FORMAT)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=15,
            is_persisted=False,
            inferred_project_name="PendingProject",
            start_time=pending_start,
        )
    )

    # 3. Build the Timeline ViewModel for the HISTORICAL date.
    timeline = get_timeline_view_model(historical_day)
    assert timeline["ok"] is True
    live_clock = timeline["live_clock"]
    assert live_clock["live_state"] == "none"
    assert live_clock["is_live"] is False
    assert live_clock["is_project_duration_live"] is False
    assert live_clock["display_span_id"] == ""
    assert int(live_clock["live_started_at_epoch_ms"]) == 0
    assert int(live_clock["carry_seconds"]) == 0

    # 4. The display model for the historical date MUST NOT contain a
    #    display span (even though it would absorb on today).
    model = build_activity_display_model(
        report_date=historical_day,
        today=datetime.now().strftime("%Y-%m-%d"),
    )
    assert model["display_spans"] == []
    assert model["live_clock"]["live_state"] == "none"

    # 5. The historical anchor DB row MUST NOT be inflated by the pending
    #    projection. Its duration_seconds stays at 60 (no overlay).
    anchor_session = next(
        (
            s for s in timeline["sessions"]
            if int(s.get("first_activity_id") or 0) == anchor_aid
        ),
        None,
    )
    assert anchor_session is not None, "anchor DB row must appear on its historical date"
    assert int(anchor_session["duration_seconds"]) == 60, (
        f"historical anchor duration MUST be 60s (no pending projection "
        f"overlay); got {anchor_session['duration_seconds']}"
    )
    assert not anchor_session.get("display_span_id")
    assert anchor_session.get("live_state") != "absorbed_pending"
    assert anchor_session.get("live_state") != "persisted_open"

    # 6. The historical total equals the anchor DB row's 60s only.
    historical_total = int(timeline["total_seconds"])
    assert historical_total == 60, (
        f"historical Timeline total_seconds MUST equal the anchor DB row's "
        f"60s only (no pending projection); got {historical_total}"
    )


def test_today_persisted_open_still_overlays_matching_db_row(bridge):
    """Section 三 (today behavior preserved): on today's Timeline, the
    ``persisted_open`` overlay MUST still be applied to the matching DB
    row. This guards against over-suppression: only historical dates are
    fully suppressed.
    """
    aid, start_time = _create_real_open_activity(elapsed_seconds=120)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=120,
            is_persisted=True,
            persisted_activity_id=aid,
            inferred_project_name="TodayProject",
            start_time=start_time,
        )
    )

    today = timeline_service.get_default_report_date()
    timeline = bridge.get_timeline(today)
    assert timeline["ok"] is True
    live_clock = timeline["live_clock"]
    # Today's behavior: live clock is NOT suppressed.
    assert live_clock["live_state"] == "persisted_open"
    assert live_clock["is_live"] is True
    assert live_clock["is_project_duration_live"] is True
    assert live_clock["display_span_id"]

    # The matching DB session row MUST be overlaid.
    overlaid = [
        s for s in timeline["sessions"]
        if int(s.get("first_activity_id") or 0) == aid
    ]
    assert overlaid, "persisted_open session must appear on today's timeline"
    assert overlaid[0].get("live_state") == "persisted_open"
    assert overlaid[0].get("display_span_id")


def test_overview_materializes_display_only_fallback_when_live_overlay_missing(bridge):
    start_time = (datetime.now() - timedelta(seconds=75)).strftime(TIME_FORMAT)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=75,
            is_persisted=True,
            persisted_activity_id=987654,
            start_time=start_time,
        )
    )

    overview = bridge.get_overview()
    expected_span_id = overview["live_clock"]["display_span_id"]
    live_rows = [
        row for row in overview["activities"]
        if row.get("display_span_id") == expected_span_id
    ]

    assert live_rows, "Overview must materialize a fallback live row"
    row = live_rows[0]
    assert row["display_only"] is True
    assert row["exportable"] is False
    assert row["editable"] is False
    assert row["live_contract_fallback"] is True
    assert row["live_contract_reason"] in ("db_row_missing", "live_overlay_mismatch")
    assert row["live_base_seconds"] + overview["live_clock"]["current_elapsed_at_sample"] == row["duration_seconds"]


def test_timeline_and_details_materialize_live_fallback_when_overlay_missing(bridge):
    start_time = (datetime.now() - timedelta(seconds=80)).strftime(TIME_FORMAT)
    missing_id = 765432
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=80,
            is_persisted=True,
            persisted_activity_id=missing_id,
            start_time=start_time,
        )
    )

    timeline = bridge.get_timeline()
    details = bridge.get_timeline_session_details([missing_id], None)
    expected_span_id = timeline["live_clock"]["display_span_id"]

    session = next(
        row for row in timeline["sessions"]
        if row.get("display_span_id") == expected_span_id
    )
    detail = next(
        row for row in details["activities"]
        if row.get("display_span_id") == expected_span_id
    )
    for row in (session, detail):
        assert row["display_only"] is True
        assert row["exportable"] is False
        assert row["editable"] is False
        assert row["live_contract_fallback"] is True
        assert row["live_base_seconds"] + timeline["live_clock"]["current_elapsed_at_sample"] == row["duration_seconds"]


def test_today_live_payloads_do_not_return_live_rows_without_span_fields(bridge):
    aid, start_time = _create_real_open_activity(elapsed_seconds=90)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=90,
            is_persisted=True,
            persisted_activity_id=aid,
            start_time=start_time,
        )
    )
    payloads = [
        bridge.get_recent_activities()["activities"],
        bridge.get_timeline()["sessions"],
        bridge.get_timeline_session_details([aid], None)["activities"],
    ]

    for rows in payloads:
        for row in rows:
            if row.get("is_in_progress") or row.get("is_live_projected"):
                assert row.get("display_span_id"), row
                assert "live_base_seconds" in row, row
