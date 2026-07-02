"""Tests for the Timeline single activity restore bridge methods.

Covers ``WebViewBridge.restore_timeline_activity`` and
``WebViewBridge.get_timeline_restorable_activities``:

- successful restore (hidden / deleted / hidden+deleted) through the bridge →
  ``worktrace.api`` path;
- invalid input (bool id, non-int, non-positive) returns
  ``{"ok": false, "error": "请选择有效的活动"}``;
- nonexistent activity returns ``活动不存在``;
- normal (not hidden / not deleted) activity returns ``该活动无需恢复``;
- in-progress activity returns ``进行中记录无法恢复``;
- race-condition / unexpected ``operation_failed`` returns ``恢复失败``
  without exposing internal detail;
- unknown ``TimelineRestoreActivityError`` code collapses to ``恢复失败``;
- error results do not contain tracebacks, SQL errors, file paths, window
  titles, clipboard data, or notes;
- the recovery list returns display-safe fields only and excludes normal /
  in-progress activities;
- the recovery list invalid date / non-string / empty returns a safe error
  with an empty list;
- the recovery list never surfaces raw window_title / file_path_hint /
  full_path / clipboard / note;
- the bridge does not import backend internals (services/db/collector/
  runtime/security/config).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from worktrace.api import timeline_api
from worktrace.api.timeline_api import TimelineRestoreActivityError
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


def _seed_closed_activity_with_resource(
    app="Excel",
    process="excel.exe",
    resource="Report.xlsx",
    start="10:00:00",
    end="10:30:00",
    day="2026-06-25",
):
    aid = activity_service.create_activity(
        app,
        process,
        resource,
        start_time=f"{day} {start}",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} {end}")
    return aid




def test_restore_timeline_activity_hidden_success(bridge):
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    result = bridge.restore_timeline_activity(aid)
    assert result["ok"] is True
    assert int(result["activity_id"]) == aid
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 0
    assert int(activity.get("is_deleted") or 0) == 0
    _assert_no_sensitive_keys(result)


def test_restore_timeline_activity_deleted_success(bridge):
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    result = bridge.restore_timeline_activity(aid)
    assert result["ok"] is True
    assert int(result["activity_id"]) == aid
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_hidden, is_deleted FROM activity_log WHERE id = ?",
            (aid,),
        ).fetchone()
    assert int(row["is_hidden"]) == 0
    assert int(row["is_deleted"]) == 0
    _assert_no_sensitive_keys(result)


def test_restore_timeline_activity_hidden_and_deleted_success(bridge):
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    activity_service.soft_delete_activity(aid)
    result = bridge.restore_timeline_activity(aid)
    assert result["ok"] is True
    assert int(result["activity_id"]) == aid
    activity = activity_service.get_activity(aid)
    assert int(activity.get("is_hidden") or 0) == 0
    assert int(activity.get("is_deleted") or 0) == 0
    _assert_no_sensitive_keys(result)




def test_restore_timeline_activity_bool_id(bridge):
    result = bridge.restore_timeline_activity(True)
    assert result["ok"] is False
    assert result["error"] == "请选择有效的活动"
    _assert_no_sensitive_keys(result)


def test_restore_timeline_activity_non_int(bridge):
    result = bridge.restore_timeline_activity("not an int")
    assert result["ok"] is False
    assert result["error"] == "请选择有效的活动"
    _assert_no_sensitive_keys(result)


def test_restore_timeline_activity_non_positive(bridge):
    result = bridge.restore_timeline_activity(0)
    assert result["ok"] is False
    assert result["error"] == "请选择有效的活动"
    _assert_no_sensitive_keys(result)
    result2 = bridge.restore_timeline_activity(-5)
    assert result2["ok"] is False
    assert result2["error"] == "请选择有效的活动"
    _assert_no_sensitive_keys(result2)


def test_restore_timeline_activity_none(bridge):
    result = bridge.restore_timeline_activity(None)
    assert result["ok"] is False
    assert result["error"] == "请选择有效的活动"
    _assert_no_sensitive_keys(result)




def test_restore_timeline_activity_nonexistent(bridge):
    result = bridge.restore_timeline_activity(999999)
    assert result["ok"] is False
    assert result["error"] == "活动不存在"
    _assert_no_sensitive_keys(result)


def test_restore_timeline_activity_normal_not_restorable(bridge):
    """An activity that is neither hidden nor deleted returns
    ``该活动无需恢复``."""
    aid = _seed_closed_activity()
    result = bridge.restore_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "该活动无需恢复"
    _assert_no_sensitive_keys(result)


def test_restore_timeline_activity_in_progress(bridge):
    """An in-progress activity returns ``进行中记录无法恢复``."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    # ``hide_activity`` itself rejects in-progress rows, so simulate a hidden
    # in-progress activity directly to exercise the restore-side guard.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (aid,),
        )
    result = bridge.restore_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "进行中记录无法恢复"
    _assert_no_sensitive_keys(result)




def test_restore_timeline_activity_operation_failed(bridge):
    """A race-condition ``operation_failed`` returns ``恢复失败`` without
    internal detail."""
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    with patch.object(
        activity_service, "restore_activity", side_effect=ValueError("restore_failed")
    ):
        result = bridge.restore_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "恢复失败"
    _assert_no_sensitive_keys(result)


def test_restore_timeline_activity_unexpected_exception_collapses(bridge):
    """An unexpected non-ValueError service exception collapses to
    ``恢复失败`` without echoing the traceback."""
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    with patch.object(
        activity_service, "restore_activity", side_effect=RuntimeError("boom")
    ):
        result = bridge.restore_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "恢复失败"
    _assert_no_sensitive_keys(result)


def test_restore_timeline_activity_unknown_error_code_collapses(bridge):
    """An unknown ``TimelineRestoreActivityError`` code must collapse to
    ``恢复失败`` so internal details are never surfaced."""
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    with patch.object(
        timeline_api,
        "restore_timeline_activity",
        side_effect=TimelineRestoreActivityError("unknown_code"),
    ):
        result = bridge.restore_timeline_activity(aid)
    assert result["ok"] is False
    assert result["error"] == "恢复失败"
    _assert_no_sensitive_keys(result)




def test_restore_timeline_activity_error_has_no_raw_fields(bridge):
    """An error payload must not contain window_title, file_path_hint,
    clipboard, note, traceback, sql, or full_path."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    # ``hide_activity`` rejects in-progress rows; set is_hidden directly so
    # the restore-side in-progress guard is exercised.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (aid,),
        )
    result = bridge.restore_timeline_activity(aid)
    payload_str = str(result)
    assert "window_title" not in payload_str.lower()
    assert "file_path_hint" not in payload_str.lower()
    assert "clipboard" not in payload_str.lower()
    assert "traceback" not in payload_str.lower()
    assert "sql" not in payload_str.lower()
    assert "a1.docx" not in payload_str.lower()
    assert "winword" not in payload_str.lower()


def test_restore_timeline_activity_not_restorable_error_has_no_raw_fields(bridge):
    """A not_restorable error payload must not leak the resource name or
    app name."""
    aid = _seed_closed_activity_with_resource(
        app="Excel", process="excel.exe", resource="Secret.xlsx"
    )
    result = bridge.restore_timeline_activity(aid)
    payload_str = str(result)
    assert "secret.xlsx" not in payload_str.lower()
    assert "excel" not in payload_str.lower()




def test_get_timeline_restorable_activities_returns_hidden(bridge):
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    assert isinstance(result["activities"], list)
    assert len(result["activities"]) == 1
    item = result["activities"][0]
    assert int(item["activity_id"]) == aid
    assert item["restore_state"] == "hidden"
    assert int(item["is_hidden"]) == 1
    assert int(item["is_deleted"]) == 0
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_returns_deleted(bridge):
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    assert len(result["activities"]) == 1
    item = result["activities"][0]
    assert int(item["activity_id"]) == aid
    assert item["restore_state"] == "deleted"
    assert int(item["is_hidden"]) == 0
    assert int(item["is_deleted"]) == 1
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_returns_hidden_and_deleted(bridge):
    aid = _seed_closed_activity()
    activity_service.hide_activity(aid)
    activity_service.soft_delete_activity(aid)
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    assert len(result["activities"]) == 1
    item = result["activities"][0]
    assert item["restore_state"] == "hidden+deleted"
    assert int(item["is_hidden"]) == 1
    assert int(item["is_deleted"]) == 1
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_excludes_normal(bridge):
    """Normal (not hidden / not deleted) activities must not appear."""
    _seed_closed_activity()
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_excludes_in_progress(bridge):
    """In-progress hidden/deleted activities must not appear."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    # ``hide_activity`` itself rejects in-progress rows, so simulate a hidden
    # in-progress activity directly to exercise the recovery-list guard.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (aid,),
        )
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_sorted_by_start_time(bridge):
    """The recovery list must be sorted by start_time ascending."""
    a1 = _seed_closed_activity(start="10:00:00", end="10:30:00")
    a2 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    activity_service.hide_activity(a1)
    activity_service.hide_activity(a2)
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    ids = [int(item["activity_id"]) for item in result["activities"]]
    assert ids == [a2, a1]
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_display_safe_fields_only(bridge):
    """Each recovery list item must only contain display-safe keys."""
    aid = _seed_closed_activity_with_resource(
        app="Excel", process="excel.exe", resource="Secret.xlsx"
    )
    activity_service.hide_activity(aid)
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    item = result["activities"][0]
    allowed_keys = {
        "activity_id",
        "start_time",
        "end_time",
        "duration",
        "app_name",
        "resource_type",
        "resource_name",
        "project_name",
        "status",
        "restore_state",
        "is_hidden",
        "is_deleted",
    }
    assert set(item.keys()) <= allowed_keys, (
        f"unexpected keys: {set(item.keys()) - allowed_keys}"
    )
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_no_raw_keys(bridge):
    """The recovery list must not surface raw ``window_title`` /
    ``file_path_hint`` / ``full_path`` keys; only the display-safe
    ``resource_name`` (file basename) is returned."""
    aid = _seed_closed_activity_with_resource(
        app="Excel", process="excel.exe", resource="SecretReport.xlsx"
    )
    activity_service.hide_activity(aid)
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    item = result["activities"][0]
    # The display-safe resource_name (file basename) is intentionally
    # surfaced; raw window_title / file_path_hint / full_path keys must
    # never appear.
    assert "window_title" not in item
    assert "file_path_hint" not in item
    assert "full_path" not in item
    assert "clipboard" not in item
    assert "note" not in item
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_excludes_other_dates(bridge):
    """The recovery list must only include activities for the given date."""
    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00", day="2026-06-25")
    a2 = _seed_closed_activity(start="09:00:00", end="09:30:00", day="2026-06-26")
    activity_service.hide_activity(a1)
    activity_service.hide_activity(a2)
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    ids = [int(item["activity_id"]) for item in result["activities"]]
    assert ids == [a1]
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_empty(bridge):
    """A date with no hidden/deleted activities returns an empty list."""
    result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is True
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)




def test_get_timeline_restorable_activities_invalid_date(bridge):
    """An invalid date string returns a safe error with an empty list."""
    result = bridge.get_timeline_restorable_activities("not-a-date")
    assert result["ok"] is False
    assert result["error"] == "加载可恢复记录失败"
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_empty_string(bridge):
    """An empty date string returns a safe error with an empty list."""
    result = bridge.get_timeline_restorable_activities("")
    assert result["ok"] is False
    assert result["error"] == "加载可恢复记录失败"
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_non_string(bridge):
    """A non-string date returns a safe error with an empty list."""
    result = bridge.get_timeline_restorable_activities(None)
    assert result["ok"] is False
    assert result["error"] == "加载可恢复记录失败"
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)

    result2 = bridge.get_timeline_restorable_activities(20260625)
    assert result2["ok"] is False
    assert result2["error"] == "加载可恢复记录失败"
    assert result2["activities"] == []
    _assert_no_sensitive_keys(result2)


def test_get_timeline_restorable_activities_invalid_date_code(bridge):
    """An ``invalid_date`` API error maps to ``日期无效``."""
    with patch.object(
        timeline_api,
        "get_timeline_restorable_activities",
        side_effect=TimelineRestoreActivityError("invalid_date"),
    ):
        result = bridge.get_timeline_restorable_activities("2026-13-45")
    assert result["ok"] is False
    assert result["error"] == "日期无效"
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_operation_failed(bridge):
    """An ``operation_failed`` API error maps to ``加载可恢复记录失败``
    with an empty list."""
    with patch.object(
        timeline_api,
        "get_timeline_restorable_activities",
        side_effect=TimelineRestoreActivityError("operation_failed"),
    ):
        result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "加载可恢复记录失败"
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_unknown_error_code_collapses(bridge):
    """An unknown error code collapses to ``加载可恢复记录失败``."""
    with patch.object(
        timeline_api,
        "get_timeline_restorable_activities",
        side_effect=TimelineRestoreActivityError("unknown_code"),
    ):
        result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "加载可恢复记录失败"
    assert result["activities"] == []
    _assert_no_sensitive_keys(result)


def test_get_timeline_restorable_activities_unexpected_exception_collapses(bridge):
    """An unexpected non-API exception collapses to ``加载可恢复记录失败``
    without echoing the traceback."""
    with patch.object(
        timeline_api,
        "get_timeline_restorable_activities",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_timeline_restorable_activities("2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "加载可恢复记录失败"
    assert result["activities"] == []
    payload_str = str(result)
    assert "boom" not in payload_str
    assert "traceback" not in payload_str.lower()
    _assert_no_sensitive_keys(result)




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
