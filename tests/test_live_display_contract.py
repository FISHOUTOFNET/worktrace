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
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from worktrace.constants import STATUS_NORMAL, TIME_FORMAT
from worktrace.services import settings_service
from worktrace.services.live_display_service import (
    _stable_live_key,
    _stable_live_key_hash,
    build_current_activity_summary,
)
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


def test_persisted_open_display_project_does_not_revert(bridge):
    """Verification item 5: when the snapshot has a concrete
    ``inferred_project_name``, the persisted open display project must
    NOT revert to unclassified.

    The unified ``build_current_activity_summary`` uses
    ``_display_project_name`` which prefers the snapshot's
    ``inferred_project_name`` over the DB fallback, so the persisted open
    display stays classified."""
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=60,
            is_persisted=True,
            persisted_activity_id=1,
            inferred_project_name="MyProject",
        )
    )
    summary = build_current_activity_summary(
        json.loads(
            settings_service.get_setting("current_activity_snapshot") or "null"
        )
    )
    assert summary["project_name"] == "MyProject"
    assert not summary["is_uncategorized"]


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
