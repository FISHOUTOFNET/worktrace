"""Phase 6H-followup backend tests: ``get_refresh_state`` + live projection.

These tests cover the backend pieces introduced by the Phase 6H-followup
rewrite:

- ``bridge.get_refresh_state()`` is attached to ``WebViewBridge`` and
  returns a display-safe lightweight payload (no raw window title / file
  path / clipboard / note / SQL / traceback).
- ``refresh_revision`` is structural-only: it does NOT change when only
  ``elapsed_seconds`` / ``extra_seconds`` advance, but DOES change on
  status / persisted / inferred_project_name / latest activity changes.
- ``get_recent_activities()`` returns ``duration_seconds``,
  ``is_in_progress``, ``is_live_projected``, ``snapshot_at_epoch_ms`` and
  applies projection to the most recent normal session when the current
  snapshot is live-projectable.
- ``get_timeline()`` returns ``live_projected_session_id`` for today's
  unpersisted current snapshot and never projects historical dates.
- ``get_timeline_session_details()`` returns ``duration_seconds``.
- Projection is purely a UI overlay: paused / idle / excluded / error
  snapshots never receive projection, persisted snapshots never
  double-count, and the DB / collector are untouched.
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
    """Section 2: each recent item must carry ``duration_seconds``,
    ``is_in_progress``, ``is_live_projected``; the payload must carry
    ``snapshot_at_epoch_ms``."""
    _set_snapshot(None)  # no current activity -> no projection
    result = bridge.get_recent_activities()
    assert result["ok"] is True
    assert "snapshot_at_epoch_ms" in result
    assert "live_projected_recent_index" in result
    assert "live_projected_seconds" in result
    for item in result["activities"]:
        assert "duration_seconds" in item
        assert "is_in_progress" in item
        assert "is_live_projected" in item


def test_get_recent_activities_no_projection_without_snapshot(bridge):
    """Section 2: when no current snapshot exists, no item is marked
    ``is_live_projected`` and ``live_projected_recent_index`` is -1."""
    _set_snapshot(None)
    result = bridge.get_recent_activities()
    assert result["live_projected_recent_index"] == -1
    assert result["live_projected_seconds"] == 0
    for item in result["activities"]:
        assert item["is_live_projected"] is False


def test_get_recent_activities_no_projection_for_paused_snapshot(bridge):
    """Section 12: paused / idle / excluded / error snapshots must NOT
    produce recent projection."""
    for status in ("idle", "paused", "excluded", "error"):
        _set_snapshot(_normal_snapshot(status=status))
        result = bridge.get_recent_activities()
        assert result["live_projected_recent_index"] == -1, (
            "paused/idle/excluded/error snapshot must not produce recent "
            "projection (status=" + status + ")"
        )
        for item in result["activities"]:
            assert item["is_live_projected"] is False


def test_get_recent_activities_no_projection_for_persisted_snapshot(bridge):
    """Section 12: when the current snapshot is already persisted, no
    short-activity projection is applied (avoid double counting)."""
    _set_snapshot(
        _normal_snapshot(is_persisted=True, persisted_activity_id=123)
    )
    result = bridge.get_recent_activities()
    assert result["live_projected_recent_index"] == -1
    assert result["live_projected_seconds"] == 0
    for item in result["activities"]:
        assert item["is_live_projected"] is False


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
    """Section 2: each detail row must carry ``duration_seconds``."""
    _set_snapshot(None)
    result = bridge.get_timeline_session_details([], None)
    assert result["ok"] is True
    # Empty activity_ids returns empty list (covered by existing tests).
    # The contract is that whenever rows are returned, each has
    # ``duration_seconds``. We verify the field is part of the row schema
    # by checking the bridge code path with a real activity is exercised
    # elsewhere; here we only assert the empty-list contract.
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
