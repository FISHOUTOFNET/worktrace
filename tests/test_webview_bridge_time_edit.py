"""Tests for the Phase 3B.1 Timeline time-correction bridge methods.

Covers ``WebViewBridge.update_timeline_activity_time`` and
``WebViewBridge.update_timeline_session_time``:

- successful writes through the bridge → worktrace.api path;
- invalid input (non-int id, bool id, bad time, in-progress activity)
  returns ``{"ok": false, "error": ...}`` with clear Chinese messages;
- multi-activity session-level correction returns the ``多活动`` message;
- error results do not contain tracebacks, SQL errors, file paths,
  window titles, or clipboard data;
- the bridge does not import backend internals (services/db/collector/
  runtime/security/config).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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


# --- update_timeline_activity_time ---------------------------------------


def test_update_activity_time_success(bridge):
    aid = _seed_closed_activity()
    result = bridge.update_timeline_activity_time(
        aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is True
    activity = activity_service.get_activity(aid)
    assert activity["start_time"] == "2026-06-25 10:00:00"
    assert activity["end_time"] == "2026-06-25 10:45:00"


def test_update_activity_time_is_json_serializable(bridge):
    aid = _seed_closed_activity()
    result = bridge.update_timeline_activity_time(
        aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    json.dumps(result)


def test_update_activity_time_invalid_id(bridge):
    # Non-int string
    result = bridge.update_timeline_activity_time(
        "abc", "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    assert "error" in result
    # Zero
    result = bridge.update_timeline_activity_time(
        0, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    # Negative
    result = bridge.update_timeline_activity_time(
        -1, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False


def test_update_activity_time_bool_id(bridge):
    """``bool`` must be rejected so ``True`` does not coerce to ``1``."""
    result = bridge.update_timeline_activity_time(
        True, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    assert "error" in result


def test_update_activity_time_nonexistent_id(bridge):
    result = bridge.update_timeline_activity_time(
        999999, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    assert "error" in result


def test_update_activity_time_invalid_time(bridge):
    aid = _seed_closed_activity()
    # Non-string
    result = bridge.update_timeline_activity_time(aid, 12345, "2026-06-25 10:45:00")
    assert result["ok"] is False
    assert result["error"] == "时间无效"
    # Empty
    result = bridge.update_timeline_activity_time(aid, "", "2026-06-25 10:45:00")
    assert result["ok"] is False
    assert result["error"] == "时间无效"
    # Wrong shape
    result = bridge.update_timeline_activity_time(aid, "bad", "2026-06-25 10:45:00")
    assert result["ok"] is False
    assert result["error"] == "时间无效"
    # Wrong separator (T instead of space)
    result = bridge.update_timeline_activity_time(
        aid, "2026-06-25T10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    assert result["error"] == "时间无效"


def test_update_activity_time_start_ge_end(bridge):
    aid = _seed_closed_activity()
    # Equal
    result = bridge.update_timeline_activity_time(
        aid, "2026-06-25 10:00:00", "2026-06-25 10:00:00"
    )
    assert result["ok"] is False
    assert "error" in result
    # End before start
    result = bridge.update_timeline_activity_time(
        aid, "2026-06-25 10:45:00", "2026-06-25 10:00:00"
    )
    assert result["ok"] is False
    assert "error" in result


def test_update_activity_time_in_progress(bridge):
    """In-progress activities must return a clear Chinese message."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.update_timeline_activity_time(
        aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持时间修正"


def test_update_activity_time_no_traceback_on_error(bridge):
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.update_timeline_activity_time",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.update_timeline_activity_time(
            aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_update_activity_time_error_has_no_sensitive_keys(bridge):
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.update_timeline_activity_time",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.update_timeline_activity_time(
            aid, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )
    _assert_no_sensitive_keys(result)


# --- update_timeline_session_time ----------------------------------------


def test_update_session_time_single_activity_success(bridge):
    aid = _seed_closed_activity()
    result = bridge.update_timeline_session_time(
        [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is True
    activity = activity_service.get_activity(aid)
    assert activity["start_time"] == "2026-06-25 10:00:00"
    assert activity["end_time"] == "2026-06-25 10:45:00"


def test_update_session_time_multi_activity_returns_clear_message(bridge):
    """Multi-activity sessions must return a clear Chinese message at the
    bridge layer (without a round-trip through the API)."""
    ids = _seed_session()
    result = bridge.update_timeline_session_time(
        ids, "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    assert result["error"] == "多活动 session 暂不支持整体时间修改"


def test_update_session_time_invalid_ids(bridge):
    # Empty list
    result = bridge.update_timeline_session_time(
        [], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    assert "error" in result
    # Non-list
    result = bridge.update_timeline_session_time(
        "not a list", "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    # List with bool
    result = bridge.update_timeline_session_time(
        [True], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False


def test_update_session_time_invalid_time(bridge):
    aid = _seed_closed_activity()
    result = bridge.update_timeline_session_time([aid], "bad", "2026-06-25 10:45:00")
    assert result["ok"] is False
    assert result["error"] == "时间无效"


def test_update_session_time_in_progress(bridge):
    """A single-activity session that is still open must return the
    in-progress message."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Open.docx", start_time="2026-06-25 09:00:00"
    )
    activity_service.finalize_created_activity(aid)
    result = bridge.update_timeline_session_time(
        [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持时间修正"


def test_update_session_time_no_traceback_on_error(bridge):
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.update_timeline_session_time",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.update_timeline_session_time(
            [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_update_session_time_error_has_no_sensitive_keys(bridge):
    aid = _seed_closed_activity()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.update_timeline_session_time",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.update_timeline_session_time(
            [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
        )
    _assert_no_sensitive_keys(result)


def test_update_session_time_is_json_serializable(bridge):
    aid = _seed_closed_activity()
    result = bridge.update_timeline_session_time(
        [aid], "2026-06-25 10:00:00", "2026-06-25 10:45:00"
    )
    json.dumps(result)


# --- Bridge import boundary ----------------------------------------------


def test_bridge_does_not_import_backend_internals():
    """The bridge module must not import services, db, collector, runtime,
    security, or config directly. It may only import from worktrace.api."""
    bridge_path = Path(__file__).resolve().parents[1] / "worktrace" / "webview_ui" / "bridge.py"
    source = bridge_path.read_text(encoding="utf-8")
    # Check import statements
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
