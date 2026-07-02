"""Tests for the Timeline hide / soft-delete bridge methods.

Covers ``WebViewBridge.hide_timeline_activity``,
``soft_delete_timeline_activity``, ``hide_timeline_session``, and
``soft_delete_timeline_session``:

- successful hide / soft delete through the bridge → worktrace.api path;
- invalid input (bool id, non-int, non-positive, non-list, empty list,
  bool id in list) returns ``{"ok": false, "error": "操作失败"}``;
- in-progress activity returns ``进行中记录暂不支持隐藏或删除``;
- multi-activity session hide returns
  ``多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理``;
- multi-activity session delete returns
  ``多活动 session 暂不支持整体删除，请在活动详情中逐条处理``;
- race-condition ``operation_failed`` returns the generic ``操作失败``
  message without exposing internal detail;
- error results do not contain tracebacks, SQL errors, file paths,
  window titles, clipboard data, or notes;
- the bridge does not import backend internals (services/db/collector/
  runtime/security/config).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineVisibilityError
from worktrace.db import get_connection
from worktrace.services import activity_service, settings_service
from worktrace.webview_ui.bridge import WebViewBridge


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    return WebViewBridge()


SENSITIVE_KEYS = (
    "window_title",
    "file_path_hint",
    "note",
    "clipboard",
    "traceback",
    "exception",
    "stack",
    "full_path",
    "sql",
)


def _assert_no_sensitive_keys(payload, label: str = "payload") -> None:
    if isinstance(payload, dict):
        for key in SENSITIVE_KEYS:
            assert key not in payload, (
                f"{label} must not expose sensitive field '{key}'; "
                f"got keys: {sorted(payload.keys())}"
            )
        for value in payload.values():
            _assert_no_sensitive_keys(value, label)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_sensitive_keys(item, label)


def _seed_closed_activity(start="09:00:00", end="09:30:00", day="2026-06-25"):
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "A1.docx",
        start_time=f"{day} {start}",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} {end}")
    return aid


def _seed_two_closed_activities(
    start1="09:00:00",
    end1="09:30:00",
    start2="09:30:00",
    end2="10:00:00",
    day="2026-06-25",
):
    a1 = _seed_closed_activity(start=start1, end=end1, day=day)
    a2 = _seed_closed_activity(start=start2, end=end2, day=day)
    return [a1, a2]


# --- hide_timeline_activity: success -------------------------------------


def test_hide_timeline_activity_success(bridge):
    aid = _seed_closed_activity()
    result = bridge.hide_timeline_activity(aid)
    assert result["ok"] is True
    # Verify the actual hide happened in the DB.
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1
    _assert_no_sensitive_keys(result)


def test_hide_timeline_activity_idempotent(bridge):
    """Hiding an already-hidden activity succeeds through the bridge."""
    aid = _seed_closed_activity()
    bridge.hide_timeline_activity(aid)
    result = bridge.hide_timeline_activity(aid)
    assert result["ok"] is True
    _assert_no_sensitive_keys(result)


# --- soft_delete_timeline_activity: success -------------------------------


def test_soft_delete_timeline_activity_success(bridge):
    aid = _seed_closed_activity()
    result = bridge.soft_delete_timeline_activity(aid)
    assert result["ok"] is True
    # Verify the actual soft delete happened in the DB.
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_deleted FROM activity_log WHERE id = ?",
            (aid,),
        ).fetchone()
    assert int(row["is_deleted"]) == 1
    _assert_no_sensitive_keys(result)


# --- hide_timeline_session / soft_delete_timeline_session: success --------


def test_hide_timeline_session_single_activity_success(bridge):
    aid = _seed_closed_activity()
    result = bridge.hide_timeline_session([aid])
    assert result["ok"] is True
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 1
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_session_single_activity_success(bridge):
    aid = _seed_closed_activity()
    result = bridge.soft_delete_timeline_session([aid])
    assert result["ok"] is True
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_deleted FROM activity_log WHERE id = ?",
            (aid,),
        ).fetchone()
    assert int(row["is_deleted"]) == 1
    _assert_no_sensitive_keys(result)


# --- hide_timeline_activity / soft_delete_timeline_activity: invalid id ---


def test_hide_timeline_activity_bool_id(bridge):
    result = bridge.hide_timeline_activity(True)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_hide_timeline_activity_non_int(bridge):
    result = bridge.hide_timeline_activity("not an int")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_hide_timeline_activity_non_positive(bridge):
    result = bridge.hide_timeline_activity(0)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_activity_bool_id(bridge):
    result = bridge.soft_delete_timeline_activity(True)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_activity_non_int(bridge):
    result = bridge.soft_delete_timeline_activity("not an int")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_activity_non_positive(bridge):
    result = bridge.soft_delete_timeline_activity(0)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


# --- in-progress ---------------------------------------------------------


def test_hide_timeline_activity_in_progress(bridge):
    """An in-progress activity returns the ``进行中`` message."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.hide_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持隐藏或删除"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_activity_in_progress(bridge):
    """An in-progress activity returns the ``进行中`` message."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.soft_delete_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持隐藏或删除"
    _assert_no_sensitive_keys(result)


# --- session-level invalid input -----------------------------------------


def test_hide_timeline_session_non_list(bridge):
    result = bridge.hide_timeline_session("not a list")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_hide_timeline_session_empty_list(bridge):
    result = bridge.hide_timeline_session([])
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_hide_timeline_session_bool_id_in_list(bridge):
    aid = _seed_closed_activity()
    result = bridge.hide_timeline_session([aid, True])
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_session_non_list(bridge):
    result = bridge.soft_delete_timeline_session("not a list")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_session_empty_list(bridge):
    result = bridge.soft_delete_timeline_session([])
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_session_bool_id_in_list(bridge):
    aid = _seed_closed_activity()
    result = bridge.soft_delete_timeline_session([aid, True])
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


# --- multi-activity session ---------------------------------------------


def test_hide_timeline_session_multi_activity(bridge):
    """A multi-activity session hide returns the dedicated Chinese message."""
    ids = _seed_two_closed_activities()
    result = bridge.hide_timeline_session(ids)
    assert result["ok"] is False
    assert result["error"] == "多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理"
    _assert_no_sensitive_keys(result)
    # Neither activity must be hidden.
    for aid in ids:
        activity = activity_service.get_activity(aid)
        assert int(activity.get("is_hidden") or 0) == 0


def test_soft_delete_timeline_session_multi_activity(bridge):
    """A multi-activity session delete returns the dedicated Chinese message."""
    ids = _seed_two_closed_activities()
    result = bridge.soft_delete_timeline_session(ids)
    assert result["ok"] is False
    assert result["error"] == "多活动 session 暂不支持整体删除，请在活动详情中逐条处理"
    _assert_no_sensitive_keys(result)
    # Neither activity must be deleted.
    for aid in ids:
        activity = activity_service.get_activity(aid)
        assert int(activity.get("is_deleted") or 0) == 0


# --- session-level in-progress ------------------------------------------


def test_hide_timeline_session_in_progress(bridge):
    """An in-progress activity in a session-level hide returns the
    ``进行中`` message."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.hide_timeline_session([aid])
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持隐藏或删除"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_session_in_progress(bridge):
    """An in-progress activity in a session-level delete returns the
    ``进行中`` message."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.soft_delete_timeline_session([aid])
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持隐藏或删除"
    _assert_no_sensitive_keys(result)


# --- operation_failed ----------------------------------------------------


def test_hide_timeline_activity_operation_failed(bridge):
    """A race-condition ``operation_failed`` returns the generic ``操作失败``
    message without internal detail."""
    aid = _seed_closed_activity()
    with patch.object(
        activity_service, "hide_activity", side_effect=ValueError("race")
    ):
        result = bridge.hide_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_activity_operation_failed(bridge):
    """A race-condition ``operation_failed`` returns the generic ``操作失败``
    message without internal detail."""
    aid = _seed_closed_activity()
    with patch.object(
        activity_service, "soft_delete_activity", side_effect=ValueError("race")
    ):
        result = bridge.soft_delete_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_hide_timeline_session_operation_failed(bridge):
    """A race-condition during a session-level hide returns ``操作失败``."""
    aid = _seed_closed_activity()
    with patch.object(
        activity_service, "hide_activity", side_effect=ValueError("race")
    ):
        result = bridge.hide_timeline_session([aid])
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_session_operation_failed(bridge):
    """A race-condition during a session-level delete returns ``操作失败``."""
    aid = _seed_closed_activity()
    with patch.object(
        activity_service, "soft_delete_activity", side_effect=ValueError("race")
    ):
        result = bridge.soft_delete_timeline_session([aid])
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


# --- Bridge error mapping exhaustiveness ---------------------------------


def test_hide_timeline_activity_unknown_error_code_collapses(bridge):
    """An unknown ``TimelineVisibilityError`` code must collapse to
    ``操作失败`` so internal details are never surfaced."""
    aid = _seed_closed_activity()
    with patch.object(
        timeline_api, "hide_timeline_activity",
        side_effect=TimelineVisibilityError("unknown_code"),
    ):
        result = bridge.hide_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_activity_unknown_error_code_collapses(bridge):
    """An unknown ``TimelineVisibilityError`` code must collapse to
    ``操作失败``."""
    aid = _seed_closed_activity()
    with patch.object(
        timeline_api, "soft_delete_timeline_activity",
        side_effect=TimelineVisibilityError("unknown_code"),
    ):
        result = bridge.soft_delete_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


# --- Bridge import boundary ----------------------------------------------


def test_bridge_does_not_import_backend_internals():
    """The bridge module must not import services, db, collector, runtime,
    security, or config directly. It may only import from worktrace.api."""
    bridge_path = Path(__file__).resolve().parents[1] / "worktrace" / "webview_ui" / "bridge.py"
    source = bridge_path.read_text(encoding="utf-8")
    forbidden_patterns = [
        r"from\s+worktrace\.services\b",
        r"import\s+worktrace\.services\b",
        r"from\s+worktrace\.db\b",
        r"import\s+worktrace\.db\b",
        r"from\s+worktrace\.collector\b",
        r"import\s+worktrace\.collector\b",
        r"from\s+worktrace\.runtime\b",
        r"import\s+worktrace\.runtime\b",
        r"from\s+worktrace\.security\b",
        r"import\s+worktrace\.security\b",
        r"from\s+worktrace\.config\b",
        r"import\s+worktrace\.config\b",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, source), (
            f"bridge.py must not import backend internals: matched {pattern}"
        )


# --- Sensitive data not in any error payload -----------------------------


def test_hide_timeline_activity_error_has_no_raw_fields(bridge):
    """An error payload must not contain window_title, file_path_hint,
    clipboard, note, traceback, sql, or full_path."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.hide_timeline_activity(aid)
    # in-progress error
    payload_str = str(result)
    assert "window_title" not in payload_str.lower()
    assert "file_path_hint" not in payload_str.lower()
    assert "clipboard" not in payload_str.lower()
    assert "traceback" not in payload_str.lower()
    assert "sql" not in payload_str.lower()
    assert "a1.docx" not in payload_str.lower()
    assert "winword" not in payload_str.lower()


def test_soft_delete_timeline_activity_error_has_no_raw_fields(bridge):
    """An error payload must not contain window_title, file_path_hint,
    clipboard, note, traceback, sql, or full_path."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.soft_delete_timeline_activity(aid)
    payload_str = str(result)
    assert "window_title" not in payload_str.lower()
    assert "file_path_hint" not in payload_str.lower()
    assert "clipboard" not in payload_str.lower()
    assert "traceback" not in payload_str.lower()
    assert "sql" not in payload_str.lower()
    assert "a1.docx" not in payload_str.lower()
    assert "winword" not in payload_str.lower()


def test_hide_timeline_session_multi_activity_error_has_no_raw_fields(bridge):
    """The multi-activity hide error must not leak raw fields."""
    ids = _seed_two_closed_activities()
    result = bridge.hide_timeline_session(ids)
    payload_str = str(result)
    assert "window_title" not in payload_str.lower()
    assert "file_path_hint" not in payload_str.lower()
    assert "clipboard" not in payload_str.lower()
    assert "traceback" not in payload_str.lower()
    assert "sql" not in payload_str.lower()
    assert "a1.docx" not in payload_str.lower()
    assert "winword" not in payload_str.lower()


def test_soft_delete_timeline_session_multi_activity_error_has_no_raw_fields(bridge):
    """The multi-activity delete error must not leak raw fields."""
    ids = _seed_two_closed_activities()
    result = bridge.soft_delete_timeline_session(ids)
    payload_str = str(result)
    assert "window_title" not in payload_str.lower()
    assert "file_path_hint" not in payload_str.lower()
    assert "clipboard" not in payload_str.lower()
    assert "traceback" not in payload_str.lower()
    assert "sql" not in payload_str.lower()
    assert "a1.docx" not in payload_str.lower()
    assert "winword" not in payload_str.lower()


# --- bridge-layer hardening ---------------------------------


def test_hide_timeline_session_multi_activity_does_not_call_api(bridge):
    """The bridge must short-circuit a multi-activity session hide without
    invoking the underlying API write path. The bridge-level guard gives
    the user an immediate clear message and avoids a needless round-trip
    through the API/service layer."""
    ids = _seed_two_closed_activities()
    with patch.object(timeline_api, "hide_timeline_session") as mock_api:
        result = bridge.hide_timeline_session(ids)
    mock_api.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_session_multi_activity_does_not_call_api(bridge):
    """The bridge must short-circuit a multi-activity session soft delete
    without invoking the underlying API write path."""
    ids = _seed_two_closed_activities()
    with patch.object(timeline_api, "soft_delete_timeline_session") as mock_api:
        result = bridge.soft_delete_timeline_session(ids)
    mock_api.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "多活动 session 暂不支持整体删除，请在活动详情中逐条处理"
    _assert_no_sensitive_keys(result)


def test_hide_timeline_activity_invalid_id_does_not_call_api(bridge):
    """An invalid activity id (non-positive) must short-circuit at the
    bridge layer without invoking the API write path."""
    with patch.object(timeline_api, "hide_timeline_activity") as mock_api:
        result = bridge.hide_timeline_activity(0)
    mock_api.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_activity_invalid_id_does_not_call_api(bridge):
    """An invalid activity id (non-positive) must short-circuit at the
    bridge layer without invoking the API write path."""
    with patch.object(timeline_api, "soft_delete_timeline_activity") as mock_api:
        result = bridge.soft_delete_timeline_activity(0)
    mock_api.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_hide_timeline_activity_bool_id_does_not_call_api(bridge):
    """A ``bool`` activity id must short-circuit at the bridge layer
    without invoking the API write path. ``bool`` is a subclass of ``int``
    and must not be coerced to ``1``/``0``."""
    with patch.object(timeline_api, "hide_timeline_activity") as mock_api:
        result = bridge.hide_timeline_activity(True)
    mock_api.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_activity_bool_id_does_not_call_api(bridge):
    """A ``bool`` activity id must short-circuit at the bridge layer
    without invoking the API write path."""
    with patch.object(timeline_api, "soft_delete_timeline_activity") as mock_api:
        result = bridge.soft_delete_timeline_activity(True)
    mock_api.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_hide_timeline_session_non_list_does_not_call_api(bridge):
    """A non-list ``activity_ids`` argument must short-circuit at the bridge
    layer without invoking the API write path."""
    with patch.object(timeline_api, "hide_timeline_session") as mock_api:
        result = bridge.hide_timeline_session("not a list")
    mock_api.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)


def test_soft_delete_timeline_session_non_list_does_not_call_api(bridge):
    """A non-list ``activity_ids`` argument must short-circuit at the bridge
    layer without invoking the API write path."""
    with patch.object(timeline_api, "soft_delete_timeline_session") as mock_api:
        result = bridge.soft_delete_timeline_session(None)
    mock_api.assert_not_called()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    _assert_no_sensitive_keys(result)
