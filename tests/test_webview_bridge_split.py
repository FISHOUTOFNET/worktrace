"""Tests for the Timeline activity-split bridge methods.

Covers ``WebViewBridge.split_timeline_activity`` and
``WebViewBridge.split_timeline_session``:

- successful splits through the bridge → worktrace.api path;
- invalid input (non-int id, bool id, bad split_time, in-progress activity)
  returns ``{"ok": false, "error": ...}`` with clear Chinese messages;
- multi-activity session-level split returns the ``多活动`` message;
- error results do not contain tracebacks, SQL errors, file paths,
  window titles, or clipboard data;
- the bridge does not import backend internals (services/db/collector/
  runtime/security/config).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from worktrace.api.timeline_api import TimelineSplitError
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


def _seed_closed_status_activity(status="idle"):
    aid = activity_service.create_activity(
        status.title(), status, f"{status} status",
        status=status,
        start_time="2026-06-25 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-25 09:30:00")
    return aid


def _seed_session():
    a1 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(a1)
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A2.docx", start_time="2026-06-25 09:10:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, "2026-06-25 09:30:00")
    return [a1, a2]




def test_split_activity_success(bridge):
    aid = _seed_closed_activity()
    result = bridge.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert result["ok"] is True
    assert result["original_activity_id"] == aid
    assert isinstance(result["new_activity_id"], int)
    assert result["new_activity_id"] != aid
    # Verify the actual split happened in the DB.
    front = activity_service.get_activity(aid)
    back = activity_service.get_activity(result["new_activity_id"])
    assert front["end_time"] == "2026-06-25 09:15:00"
    assert back["start_time"] == "2026-06-25 09:15:00"
    assert back["end_time"] == "2026-06-25 09:30:00"


def test_split_activity_is_json_serializable(bridge):
    aid = _seed_closed_activity()
    result = bridge.split_timeline_activity(aid, "2026-06-25 09:15:00")
    json.dumps(result)


def test_split_activity_invalid_id(bridge):
    # Non-int string
    result = bridge.split_timeline_activity("abc", "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert "error" in result
    # Zero
    result = bridge.split_timeline_activity(0, "2026-06-25 09:15:00")
    assert result["ok"] is False
    # Negative
    result = bridge.split_timeline_activity(-1, "2026-06-25 09:15:00")
    assert result["ok"] is False


def test_split_activity_bool_id(bridge):
    """``bool`` must be rejected so ``True`` does not coerce to ``1``."""
    result = bridge.split_timeline_activity(True, "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert "error" in result


def test_split_activity_nonexistent_id(bridge):
    result = bridge.split_timeline_activity(999999, "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert "error" in result


def test_split_activity_invalid_time(bridge):
    aid = _seed_closed_activity()
    # Non-string
    result = bridge.split_timeline_activity(aid, 12345)
    assert result["ok"] is False
    assert result["error"] == "拆分时间无效"
    # Empty
    result = bridge.split_timeline_activity(aid, "")
    assert result["ok"] is False
    assert result["error"] == "拆分时间无效"
    # Wrong shape
    result = bridge.split_timeline_activity(aid, "bad")
    assert result["ok"] is False
    assert result["error"] == "拆分时间无效"
    # Wrong separator (T instead of space)
    result = bridge.split_timeline_activity(aid, "2026-06-25T09:15:00")
    assert result["ok"] is False
    assert result["error"] == "拆分时间无效"


def test_split_activity_split_outside_range(bridge):
    """split_time outside the activity range must return a clear error."""
    aid = _seed_closed_activity(start="09:00:00", end="09:30:00")
    # Equal to start
    result = bridge.split_timeline_activity(aid, "2026-06-25 09:00:00")
    assert result["ok"] is False
    assert result["error"] == "拆分时间无效"
    # Equal to end
    result = bridge.split_timeline_activity(aid, "2026-06-25 09:30:00")
    assert result["ok"] is False
    assert result["error"] == "拆分时间无效"


def test_split_activity_in_progress(bridge):
    """In-progress activities must return the clear Chinese message."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持拆分"


def test_split_activity_system_status_returns_contract_message(bridge):
    aid = _seed_closed_status_activity("idle")

    result = bridge.split_timeline_activity(aid, "2026-06-25 09:15:00")

    assert result == {"ok": False, "error": "系统状态记录不支持项目编辑"}


def test_split_activity_deleted(bridge):
    """Deleted activities must return the generic ``操作失败`` message
    (the ``invalid_id`` code collapses to ``操作失败`` so the user is not
    told whether the id was missing vs deleted)."""
    aid = _seed_closed_activity()
    activity_service.soft_delete_activity(aid)
    result = bridge.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert result["error"] == "操作失败"


def test_split_activity_no_traceback_on_error(bridge):
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.split_timeline_activity",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_split_activity_error_has_no_sensitive_keys(bridge):
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.split_timeline_activity",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.split_timeline_activity(aid, "2026-06-25 09:15:00")
    _assert_no_sensitive_keys(result)


def test_split_activity_race_condition_returns_generic_error(bridge):
    """When the API raises ``TimelineSplitError("operation_failed")`` due
    to a race condition, the bridge must return the generic ``操作失败``
    message without exposing that a race occurred or any internal detail."""
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.split_timeline_activity",
        side_effect=TimelineSplitError("operation_failed"),
    ):
        result = bridge.split_timeline_activity(aid, "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "race" not in str(result).lower()
    assert "operation_failed" not in str(result)




def test_split_session_single_activity_success(bridge):
    aid = _seed_closed_activity()
    result = bridge.split_timeline_session([aid], "2026-06-25 09:15:00")
    assert result["ok"] is True
    assert result["original_activity_id"] == aid
    assert isinstance(result["new_activity_id"], int)
    front = activity_service.get_activity(aid)
    back = activity_service.get_activity(result["new_activity_id"])
    assert front["end_time"] == "2026-06-25 09:15:00"
    assert back["start_time"] == "2026-06-25 09:15:00"


def test_split_session_multi_activity_returns_clear_message(bridge):
    """Multi-activity sessions must return the clear Chinese message at
    the bridge layer (without a round-trip through the API)."""
    ids = _seed_session()
    result = bridge.split_timeline_session(ids, "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert result["error"] == "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动"


def test_split_session_invalid_ids(bridge):
    # Empty list
    result = bridge.split_timeline_session([], "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert "error" in result
    # Non-list
    result = bridge.split_timeline_session("not a list", "2026-06-25 09:15:00")
    assert result["ok"] is False
    # List with bool
    result = bridge.split_timeline_session([True], "2026-06-25 09:15:00")
    assert result["ok"] is False


def test_split_session_invalid_time(bridge):
    aid = _seed_closed_activity()
    result = bridge.split_timeline_session([aid], "bad")
    assert result["ok"] is False
    assert result["error"] == "拆分时间无效"


def test_split_session_in_progress(bridge):
    """A single-activity session that is still open must return the
    in-progress message."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.split_timeline_session([aid], "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持拆分"


def test_split_session_system_status_returns_contract_message(bridge):
    aid = _seed_closed_status_activity("paused")

    result = bridge.split_timeline_session([aid], "2026-06-25 09:15:00")

    assert result == {"ok": False, "error": "系统状态记录不支持项目编辑"}


def test_split_session_no_traceback_on_error(bridge):
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.split_timeline_session",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.split_timeline_session([aid], "2026-06-25 09:15:00")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_split_session_error_has_no_sensitive_keys(bridge):
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.split_timeline_session",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.split_timeline_session([aid], "2026-06-25 09:15:00")
    _assert_no_sensitive_keys(result)


def test_split_session_is_json_serializable(bridge):
    aid = _seed_closed_activity()
    result = bridge.split_timeline_session([aid], "2026-06-25 09:15:00")
    json.dumps(result)




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
