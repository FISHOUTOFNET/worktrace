"""Phase 6H-followup / Phase R3 backend tests: unified live display model.

These tests cover the unified live-display contract introduced by the
Phase R3 rewrite (``worktrace.services.live_display_service``):

- ``bridge.get_refresh_state()`` is attached to ``WebViewBridge`` and
  returns a display-safe lightweight payload (no raw window title / file
  path / clipboard / note / SQL / traceback).
- ``refresh_revision`` is structural-only: it does NOT change when only
  ``elapsed_seconds`` / ``extra_seconds`` advance, but DOES change on
  status / persisted / inferred_project_name / latest activity / carry
  state / collector status / user_paused changes.
- ``get_recent_activities()`` returns the unified live-display payload
  (``live_display``, ``baseline_epoch_ms``) and each item carries
  ``duration_seconds``, ``is_in_progress``, ``is_virtual``,
  ``is_virtual_live``, ``live_display_key``, ``activity_id``,
  ``source``, ``edit_disabled``. A virtual live item is prepended when
  the current snapshot is a normal unpersisted activity.
- ``get_timeline()`` prepends a virtual live session for today's
  unpersisted normal snapshot and never projects historical dates.
- ``get_timeline_session_details()`` returns a virtual detail row when
  ``activity_ids`` is empty and the snapshot is eligible; real DB rows
  carry the unified flags.
- Projection is purely a UI overlay: paused / idle / excluded / error
  snapshots never produce virtual items / sessions / detail rows,
  persisted snapshots never double-count, and the DB / collector are
  untouched.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from worktrace import db
from worktrace.constants import STATUS_NORMAL, TIME_FORMAT
from worktrace.services import settings_service
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
    """Write the current-activity snapshot setting."""
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
    """Build a current-activity snapshot dict with the given fields.

    ``start_time`` defaults to ``now - elapsed_seconds`` so the
    ``snapshot_elapsed_seconds`` helper returns a positive value.
    """
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


# --- get_refresh_state: payload shape --------------------------------------


def test_get_refresh_state_attached_to_webview_bridge(bridge):
    """Section 3: ``get_refresh_state`` must be a method on
    ``WebViewBridge`` so the frontend can call it via the pywebview API."""
    assert callable(getattr(bridge, "get_refresh_state", None)), (
        "WebViewBridge must expose get_refresh_state as a callable method"
    )


def test_get_refresh_state_returns_dict_with_required_fields(bridge):
    """Section 3: ``get_refresh_state`` must return a display-safe small
    payload with the structural fields the heartbeat needs."""
    result = bridge.get_refresh_state()
    assert isinstance(result, dict)
    assert result["ok"] is True
    for field in (
        "collector_status",
        "paused",
        "status_display",
        "current_activity_key",
        "current_activity_status",
        "is_persisted",
        "persisted_activity_id",
        "inferred_project_name",
        "refresh_revision",
        "today",
        "latest_activity_id",
        "snapshot_baseline_epoch_ms",
    ):
        assert field in result, "get_refresh_state missing field: " + field


def test_get_refresh_state_is_json_serializable(bridge):
    import json
    json.dumps(bridge.get_refresh_state())


def test_get_refresh_state_does_not_leak_sensitive_fields(bridge):
    """Section 4: ``get_refresh_state`` must NOT return raw window title,
    file path, clipboard, note, SQL, or traceback. The payload is
    display-safe."""
    _set_snapshot(
        {
            **_normal_snapshot(),
            "window_title": "secret.docx - Microsoft Word",
            "file_path_hint": "C:\\Users\\secret\\file.docx",
            "clipboard": "secret clipboard",
            "note": "secret note",
        }
    )
    result = bridge.get_refresh_state()
    serialized = json.dumps(result)
    for forbidden in (
        "secret.docx",
        "Microsoft Word",
        "C:\\Users\\secret",
        "file.docx",
        "secret clipboard",
        "secret note",
        "window_title",
        "file_path_hint",
        "clipboard",
        "note",
        "traceback",
    ):
        assert forbidden not in serialized, (
            "get_refresh_state leaked sensitive field: " + forbidden
        )


def test_get_refresh_state_returns_generic_error_on_failure(bridge):
    """Section 3: on exception, ``get_refresh_state`` must return a generic
    error payload without traceback."""
    with patch(
        "worktrace.api.settings_api.get_collector_status",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_refresh_state()
    assert result["ok"] is False
    assert "boom" not in json.dumps(result)
    assert "traceback" not in json.dumps(result).lower()


# --- refresh_revision semantics -------------------------------------------


def test_refresh_revision_unchanged_when_only_elapsed_advances(bridge):
    """Section 4: ``refresh_revision`` must NOT change when only
    ``elapsed_seconds`` / ``extra_seconds`` advance within the same
    activity. Natural time progression must not trigger a heavy refresh.

    The ``current_activity_key`` includes ``start_time`` (a structural
    field that identifies the activity), so this test fixes ``start_time``
    and only varies the ``elapsed_seconds`` fallback field + the
    ``extra_seconds`` carry field. Both are time-elapsed fields that
    MUST NOT contribute to ``refresh_revision``."""
    fixed_start = (datetime.now() - timedelta(seconds=300)).strftime(TIME_FORMAT)
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=100, extra_seconds=0, start_time=fixed_start
        )
    )
    r1 = bridge.get_refresh_state()
    _set_snapshot(
        _normal_snapshot(
            elapsed_seconds=200, extra_seconds=50, start_time=fixed_start
        )
    )
    r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] == r2["refresh_revision"], (
        "refresh_revision must not change when only elapsed_seconds / "
        "extra_seconds advance within the same activity"
    )


def test_refresh_revision_changes_on_status_change(bridge):
    """Section 4: ``refresh_revision`` must change when the current
    activity status changes (e.g. normal -> idle)."""
    _set_snapshot(_normal_snapshot(status=STATUS_NORMAL))
    r1 = bridge.get_refresh_state()
    _set_snapshot(_normal_snapshot(status="idle"))
    r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] != r2["refresh_revision"], (
        "refresh_revision must change on current activity status change"
    )


def test_refresh_revision_changes_on_persisted_state(bridge):
    """Section 4: ``refresh_revision`` must change when the current
    activity's persisted state changes (unpersisted -> persisted)."""
    _set_snapshot(_normal_snapshot(is_persisted=False, persisted_activity_id=0))
    r1 = bridge.get_refresh_state()
    _set_snapshot(_normal_snapshot(is_persisted=True, persisted_activity_id=42))
    r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] != r2["refresh_revision"], (
        "refresh_revision must change on persisted state change"
    )


def test_refresh_revision_changes_on_persisted_activity_id(bridge):
    """Section 4: ``refresh_revision`` must change when
    ``persisted_activity_id`` changes (even if both are persisted)."""
    _set_snapshot(
        _normal_snapshot(is_persisted=True, persisted_activity_id=42)
    )
    r1 = bridge.get_refresh_state()
    _set_snapshot(
        _normal_snapshot(is_persisted=True, persisted_activity_id=99)
    )
    r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] != r2["refresh_revision"], (
        "refresh_revision must change on persisted_activity_id change"
    )


def test_refresh_revision_changes_on_inferred_project_name(bridge):
    """Section 4: ``refresh_revision`` must change when
    ``inferred_project_name`` changes (the activity was reclassified)."""
    _set_snapshot(_normal_snapshot(inferred_project_name="ProjectA"))
    r1 = bridge.get_refresh_state()
    _set_snapshot(_normal_snapshot(inferred_project_name="ProjectB"))
    r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] != r2["refresh_revision"], (
        "refresh_revision must change on inferred_project_name change"
    )


def test_refresh_revision_changes_on_collector_status(bridge):
    """Section 4: ``refresh_revision`` must change when collector_status
    changes (e.g. running -> paused)."""
    settings_service.set_setting("collector_status", "running")
    settings_service.clear_settings_cache()
    r1 = bridge.get_refresh_state()
    settings_service.set_setting("collector_status", "paused")
    settings_service.clear_settings_cache()
    r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] != r2["refresh_revision"], (
        "refresh_revision must change on collector_status change"
    )


def test_refresh_revision_changes_on_user_paused(bridge):
    """Section 4: ``refresh_revision`` must change when user_paused flips."""
    settings_service.set_setting("user_paused", "false")
    settings_service.clear_settings_cache()
    r1 = bridge.get_refresh_state()
    settings_service.set_setting("user_paused", "true")
    settings_service.clear_settings_cache()
    r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] != r2["refresh_revision"], (
        "refresh_revision must change on user_paused change"
    )


# --- get_recent_activities: projection ------------------------------------


def test_get_recent_activities_returns_required_fields(bridge):
    """Section 2: each recent item must carry the unified live-display
    fields; the payload must carry ``live_display``,
    ``baseline_epoch_ms``, and ``snapshot_at_epoch_ms``."""
    _set_snapshot(None)  # no current activity -> no virtual item
    result = bridge.get_recent_activities()
    assert result["ok"] is True
    assert "snapshot_at_epoch_ms" in result
    assert "baseline_epoch_ms" in result
    assert "live_display" in result
    for item in result["activities"]:
        assert "duration_seconds" in item
        assert "is_in_progress" in item
        assert "is_live_projected" in item
        assert "is_virtual" in item
        assert "is_virtual_live" in item
        assert "live_display_key" in item
        assert "activity_id" in item
        assert "source" in item
        assert "edit_disabled" in item


def test_get_recent_activities_no_projection_without_snapshot(bridge):
    """Section 2: when no current snapshot exists, no virtual item is
    prepended and ``live_display.is_virtual_live`` is False."""
    _set_snapshot(None)
    result = bridge.get_recent_activities()
    assert result["live_display"]["is_virtual_live"] is False
    for item in result["activities"]:
        assert item["is_virtual_live"] is False
        assert item["is_virtual"] is False


def test_get_recent_activities_no_projection_for_paused_snapshot(bridge):
    """Section 12: paused / idle / excluded / error snapshots must NOT
    produce a virtual recent item."""
    for status in ("idle", "paused", "excluded", "error"):
        _set_snapshot(_normal_snapshot(status=status))
        result = bridge.get_recent_activities()
        assert result["live_display"]["is_virtual_live"] is False, (
            "paused/idle/excluded/error snapshot must not produce a "
            "virtual recent item (status=" + status + ")"
        )
        for item in result["activities"]:
            assert item["is_virtual_live"] is False
            assert item["is_virtual"] is False


def test_get_recent_activities_no_projection_for_persisted_snapshot(bridge):
    """Section 12: when the current snapshot is already persisted, no
    virtual item is prepended (avoid double counting). The real
    persisted-open DB row (if any) carries ``is_in_progress``."""
    _set_snapshot(
        _normal_snapshot(is_persisted=True, persisted_activity_id=123)
    )
    result = bridge.get_recent_activities()
    assert result["live_display"]["is_virtual_live"] is False
    for item in result["activities"]:
        assert item["is_virtual_live"] is False
        assert item["is_virtual"] is False


# --- get_timeline: projection ---------------------------------------------


def test_get_timeline_returns_required_projection_fields(bridge):
    """Section 2: ``get_timeline`` payload must carry
    ``live_projected_session_id`` and ``live_projected_seconds``."""
    _set_snapshot(None)
    result = bridge.get_timeline()
    assert result["ok"] is True
    assert "live_projected_session_id" in result
    assert "live_projected_seconds" in result
    assert "snapshot_at_epoch_ms" in result
    for s in result["sessions"]:
        assert "duration_seconds" in s
        assert "is_in_progress" in s
        assert "is_live_projected" in s


def test_get_timeline_does_not_project_historical_date(bridge):
    """Section 12: historical dates must NOT be live-projected. Only today
    is eligible for projection."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    result = bridge.get_timeline(yesterday)
    assert result["ok"] is True
    assert result["live_projected_session_id"] == ""
    assert result["live_projected_seconds"] == 0
    for s in result["sessions"]:
        assert s["is_live_projected"] is False


def test_get_timeline_no_projection_for_persisted_snapshot(bridge):
    """Section 12: when the current snapshot is already persisted, no
    short-activity projection is applied (avoid double counting). The
    real ``is_in_progress`` session alone carries the live duration."""
    _set_snapshot(
        _normal_snapshot(is_persisted=True, persisted_activity_id=123)
    )
    result = bridge.get_timeline()
    assert result["live_projected_session_id"] == ""
    assert result["live_projected_seconds"] == 0


def test_get_timeline_no_projection_for_paused_snapshot(bridge):
    """Section 12: paused / idle / excluded / error snapshots must NOT
    produce Timeline projection."""
    for status in ("idle", "paused", "excluded", "error"):
        _set_snapshot(_normal_snapshot(status=status))
        result = bridge.get_timeline()
        assert result["live_projected_session_id"] == "", (
            "paused/idle/excluded/error snapshot must not produce Timeline "
            "projection (status=" + status + ")"
        )
        assert result["live_projected_seconds"] == 0


# --- get_timeline_session_details: duration_seconds -----------------------


def test_get_timeline_session_details_returns_duration_seconds(bridge):
    """Section 2: each detail row must carry ``duration_seconds`` and the
    unified live-display fields. With no snapshot, no virtual row is
    produced so the list is empty (the per-row schema is exercised by the
    virtual-row test below)."""
    _set_snapshot(None)
    result = bridge.get_timeline_session_details([], None)
    assert result["ok"] is True
    assert result["activities"] == []


def test_get_timeline_session_details_no_sensitive_fields(bridge):
    """Section 2: detail rows must NOT leak raw title / path / note."""
    _set_snapshot(None)
    result = bridge.get_timeline_session_details([], None)
    serialized = json.dumps(result)
    for forbidden in ("window_title", "file_path_hint", "note", "clipboard"):
        assert forbidden not in serialized


# --- bridge boundary: get_refresh_state only uses facade -----------------


def test_get_refresh_state_bridge_method_is_on_webview_bridge():
    """Section 3 / 13: ``get_refresh_state`` must be a method on the
    ``WebViewBridge`` class so the frontend can call
    ``window.pywebview.api.get_refresh_state()``."""
    assert hasattr(WebViewBridge, "get_refresh_state")
    assert callable(getattr(WebViewBridge, "get_refresh_state"))


def test_get_refresh_state_is_json_serializable_with_snapshot(bridge):
    """The payload must remain JSON-serializable even when a snapshot is
    set (so the bridge can return it to the frontend)."""
    _set_snapshot(_normal_snapshot())
    import json
    json.dumps(bridge.get_refresh_state())


# --- Phase R3: unified virtual live display contract --------------------


def test_get_recent_activities_prepends_virtual_item_for_normal_snapshot(bridge):
    """Phase R3: when the current snapshot is a normal unpersisted
    activity, ``get_recent_activities`` must prepend a virtual live item
    with ``is_virtual`` / ``is_virtual_live`` True, ``activity_id`` 0,
    ``source`` "snapshot", ``edit_disabled`` True, and a non-empty
    ``live_display_key``. The DB is never written."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    result = bridge.get_recent_activities()
    assert result["ok"] is True
    assert result["live_display"]["is_virtual_live"] is True
    items = result["activities"]
    assert len(items) >= 1, "virtual live item must be prepended"
    virtual = items[0]
    assert virtual["is_virtual"] is True
    assert virtual["is_virtual_live"] is True
    assert virtual["activity_id"] == 0
    assert virtual["source"] == "snapshot"
    assert virtual["edit_disabled"] is True
    assert virtual["is_in_progress"] is True
    assert virtual["live_display_key"]
    assert virtual["duration_seconds"] > 0


def test_get_timeline_prepends_virtual_session_for_normal_snapshot(bridge):
    """Phase R3: when the current snapshot is a normal unpersisted
    activity, ``get_timeline`` must prepend a virtual live session.
    ``today_total_seconds`` must include the virtual session's baseline so
    the displayed total is non-zero even when there are no DB sessions."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    result = bridge.get_timeline()
    assert result["ok"] is True
    assert result["live_projected_session_id"] == "virtual-live"
    assert result["live_projected_seconds"] > 0
    sessions = result["sessions"]
    assert len(sessions) >= 1, "virtual live session must be prepended"
    virtual = sessions[0]
    assert virtual["is_virtual"] is True
    assert virtual["is_virtual_live"] is True
    assert virtual["source"] == "snapshot"
    assert virtual["edit_disabled"] is True
    assert virtual["is_in_progress"] is True
    assert virtual["live_display_key"]
    # Timeline total must not be 0 when a virtual session exists.
    assert int(result["today_total_seconds"]) > 0
    # The virtual session's duration must be included in the total.
    assert int(result["today_total_seconds"]) >= int(virtual["duration_seconds"])


def test_get_timeline_session_details_returns_virtual_detail_row(bridge):
    """Phase R3: when ``activity_ids`` is empty and the current snapshot
    is a normal unpersisted activity, ``get_timeline_session_details``
    must return a single virtual detail row. The row uses the snapshot's
    display-safe resource/app/project — it is NEVER projected onto an old
    DB row. ``activity_id`` must be 0 and ``edit_disabled`` must be True."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    result = bridge.get_timeline_session_details([], None)
    assert result["ok"] is True
    rows = result["activities"]
    assert len(rows) == 1, "exactly one virtual detail row must be returned"
    row = rows[0]
    assert row["is_virtual"] is True
    assert row["is_virtual_live"] is True
    assert row["activity_id"] == 0
    assert row["source"] == "snapshot"
    assert row["edit_disabled"] is True
    assert row["is_in_progress"] is True
    assert row["live_display_key"]
    assert row["duration_seconds"] > 0
    # The virtual row must use the snapshot's display-safe project, not a
    # stale DB row.
    assert row["project_name"] == "TestProject"


def test_virtual_items_do_not_leak_sensitive_fields(bridge):
    """Phase R3: virtual items / sessions / detail rows must NOT leak raw
    window_title / file_path_hint / clipboard / note VALUES / SQL /
    traceback. Note: ``session_note`` is a legitimate display-safe field
    name; the check targets the raw ``note`` KEY and the sensitive VALUES."""
    _set_snapshot(
        {
            **_normal_snapshot(elapsed_seconds=120),
            "window_title": "secret.docx - Microsoft Word",
            "file_path_hint": "C:\\Users\\secret\\file.docx",
            "clipboard": "secret clipboard",
            "note": "secret note",
        }
    )
    serialized = json.dumps(bridge.get_recent_activities())
    serialized += json.dumps(bridge.get_timeline())
    serialized += json.dumps(bridge.get_timeline_session_details([], None))
    for forbidden in (
        "secret.docx",
        "Microsoft Word",
        "C:\\Users\\secret",
        "file.docx",
        "secret clipboard",
        "secret note",
        "window_title",
        "file_path_hint",
        "clipboard",
        "traceback",
    ):
        assert forbidden not in serialized, (
            "virtual item leaked sensitive field: " + forbidden
        )
    # The raw "note" KEY (as opposed to "session_note") must not appear.
    # Use a word-boundary check so "session_note" does not match.
    import re
    assert not re.search(r'(?<!session_)"note":', serialized), (
        "virtual item leaked raw note key (not session_note)"
    )


def test_refresh_revision_changes_on_pending_short_seconds(bridge):
    """Phase R3: ``refresh_revision`` must change when
    ``pending_short_seconds`` changes (the carry state advances so a
    short activity that just crossed the threshold triggers a refresh)."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    settings_service.set_setting("pending_short_seconds", "0")
    settings_service.clear_settings_cache()
    r1 = bridge.get_refresh_state()
    settings_service.set_setting("pending_short_seconds", "45")
    settings_service.clear_settings_cache()
    r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] != r2["refresh_revision"], (
        "refresh_revision must change on pending_short_seconds change"
    )


def test_refresh_revision_changes_on_date_rollover(bridge):
    """Phase R3: ``refresh_revision`` must change when ``today`` changes
    (date rollover at midnight)."""
    _set_snapshot(_normal_snapshot(elapsed_seconds=120))
    from worktrace.api import timeline_api
    with patch.object(timeline_api, "get_default_report_date", return_value="2026-06-30"):
        r1 = bridge.get_refresh_state()
    with patch.object(timeline_api, "get_default_report_date", return_value="2026-07-01"):
        r2 = bridge.get_refresh_state()
    assert r1["refresh_revision"] != r2["refresh_revision"], (
        "refresh_revision must change on date rollover"
    )
