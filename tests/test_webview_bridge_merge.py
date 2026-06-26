"""Tests for the Phase 3B.3 Timeline activity-merge bridge method.

Covers ``WebViewBridge.merge_timeline_activities``:

- successful merge through the bridge → worktrace.api path;
- invalid input (non-list, fewer than two, more than two, bool id, non-int)
  returns ``{"ok": false, "error": ...}`` with clear Chinese messages;
- in-progress activity returns the ``进行中`` message;
- different project / different resource / incompatible activity / not
  adjacent return the corresponding clear Chinese messages;
- race-condition ``operation_failed`` returns the generic ``操作失败``
  message without exposing internal detail;
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

from worktrace.api.timeline_api import TimelineMergeError
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


def _seed_two_adjacent_activities(
    start1="09:00:00",
    end1="09:30:00",
    start2="09:30:00",
    end2="10:00:00",
    day="2026-06-25",
):
    """Seed two adjacent closed activities sharing app/process/window_title
    so they satisfy all merge preconditions by default."""
    a1 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time=f"{day} {start1}"
    )
    activity_service.finalize_created_activity(a1)
    activity_service.close_activity(a1, f"{day} {end1}")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time=f"{day} {start2}"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, f"{day} {end2}")
    return [a1, a2]


# --- merge_timeline_activities: success ----------------------------------


def test_merge_success(bridge):
    ids = _seed_two_adjacent_activities()
    result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is True
    assert result["kept_activity_id"] == ids[0]
    assert result["merged_activity_id"] == ids[1]
    # Verify the actual merge happened in the DB.
    kept = activity_service.get_activity(ids[0])
    assert kept["end_time"] == "2026-06-25 10:00:00"
    # The later activity was soft-deleted.
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_deleted FROM activity_log WHERE id = ?",
            (ids[1],),
        ).fetchone()
    assert int(row["is_deleted"]) == 1


def test_merge_is_json_serializable(bridge):
    ids = _seed_two_adjacent_activities()
    result = bridge.merge_timeline_activities(ids)
    json.dumps(result)


# --- merge_timeline_activities: invalid selection ------------------------


def test_merge_non_list_activity_ids(bridge):
    result = bridge.merge_timeline_activities("not a list")
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"


def test_merge_bool_activity_ids(bridge):
    """``bool`` must be rejected at the bridge layer."""
    result = bridge.merge_timeline_activities(True)
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"


def test_merge_empty_list(bridge):
    result = bridge.merge_timeline_activities([])
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"


def test_merge_single_activity(bridge):
    """Fewer than two ids must fail with the clear message."""
    aid = _seed_closed_activity()
    result = bridge.merge_timeline_activities([aid])
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"


def test_merge_three_activities(bridge):
    """More than two ids must fail with the clear message."""
    ids = _seed_two_adjacent_activities()
    a3 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 10:00:00"
    )
    activity_service.finalize_created_activity(a3)
    activity_service.close_activity(a3, "2026-06-25 10:30:00")
    result = bridge.merge_timeline_activities(ids + [a3])
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"


def test_merge_bool_id_in_list(bridge):
    """A ``bool`` element in the list must be rejected."""
    aid = _seed_closed_activity()
    result = bridge.merge_timeline_activities([aid, True])
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"


def test_merge_non_positive_id(bridge):
    aid = _seed_closed_activity()
    result = bridge.merge_timeline_activities([aid, 0])
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"
    result = bridge.merge_timeline_activities([aid, -1])
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"


def test_merge_same_id_duplicated(bridge):
    """Duplicate ids that resolve to one id must fail."""
    aid = _seed_closed_activity()
    result = bridge.merge_timeline_activities([aid, aid])
    assert result["ok"] is False
    assert result["error"] == "请选择两个活动进行合并"


# --- merge_timeline_activities: clear error messages ---------------------


def test_merge_nonexistent_id_returns_generic(bridge):
    """A nonexistent id must collapse to the generic ``操作失败`` so the
    user is not told whether the id was missing vs deleted."""
    aid = _seed_closed_activity()
    result = bridge.merge_timeline_activities([aid, 999999])
    assert result["ok"] is False
    assert result["error"] == "操作失败"


def test_merge_deleted_activity_returns_generic(bridge):
    """A deleted activity must collapse to ``操作失败``."""
    ids = _seed_two_adjacent_activities()
    activity_service.soft_delete_activity(ids[1])
    result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "操作失败"


def test_merge_in_progress_returns_clear_message(bridge):
    """An in-progress activity must return the clear ``进行中`` message."""
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    # a2 is still open (end_time IS NULL)
    result = bridge.merge_timeline_activities([a1, a2])
    assert result["ok"] is False
    assert result["error"] == "进行中记录暂不支持合并"


def test_merge_different_project_returns_clear_message(bridge):
    ids = _seed_two_adjacent_activities()
    from worktrace.services import project_service

    project = project_service.create_project("OtherProj")
    activity_service.update_activity_project(ids[1], project, manual=True)
    result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "项目不同，暂不支持合并"


def test_merge_different_resource_returns_clear_message(bridge):
    ids = _seed_two_adjacent_activities()
    # Change the second activity's resource identity_key so resources differ.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_resource SET identity_key = ? WHERE activity_id = ?",
            ("different_identity_key", ids[1]),
        )
    result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "资源不同，暂不支持合并"


def test_merge_incompatible_activity_status_returns_clear_message(bridge):
    ids = _seed_two_adjacent_activities()
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET status = 'idle' WHERE id = ?",
            (ids[1],),
        )
    result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "活动类型不同，暂不支持合并"


def test_merge_incompatible_activity_source_returns_clear_message(bridge):
    ids = _seed_two_adjacent_activities()
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET source = 'manual' WHERE id = ?",
            (ids[1],),
        )
    result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "活动类型不同，暂不支持合并"


def test_merge_not_adjacent_returns_clear_message(bridge):
    """A gap larger than the tolerance must return the clear message."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00",
        start2="10:00:00", end2="10:30:00",
    )
    result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "活动时间不连续，暂不支持合并"


def test_merge_overlap_returns_invalid_time(bridge):
    """Overlap must collapse to ``时间无效`` (invalid_time code)."""
    ids = _seed_two_adjacent_activities(
        start1="09:00:00", end1="09:30:00",
        start2="09:20:00", end2="10:00:00",
    )
    result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "时间无效"


def test_merge_operation_failed_returns_generic(bridge):
    """When the API raises ``TimelineMergeError("operation_failed")`` due
    to a race condition, the bridge must return the generic ``操作失败``
    message without exposing that a race occurred or any internal detail."""
    ids = _seed_two_adjacent_activities()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.merge_timeline_activities",
        side_effect=TimelineMergeError("operation_failed"),
    ):
        result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "race" not in str(result).lower()
    assert "operation_failed" not in str(result)


# --- merge_timeline_activities: privacy / safety -------------------------


def test_merge_no_traceback_on_error(bridge):
    """Unexpected exceptions must collapse to the generic message without
    surfacing the exception string."""
    ids = _seed_two_adjacent_activities()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.merge_timeline_activities",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.merge_timeline_activities(ids)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_merge_error_has_no_sensitive_keys(bridge):
    ids = _seed_two_adjacent_activities()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.merge_timeline_activities",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.merge_timeline_activities(ids)
    _assert_no_sensitive_keys(result)


def test_merge_success_has_no_sensitive_keys(bridge):
    """Success results must not leak sensitive fields either."""
    ids = _seed_two_adjacent_activities()
    result = bridge.merge_timeline_activities(ids)
    _assert_no_sensitive_keys(result)


def test_merge_reversed_argument_order_still_correct(bridge):
    """Passing the ids in reverse order must still keep the earlier one."""
    ids = _seed_two_adjacent_activities()
    result = bridge.merge_timeline_activities([ids[1], ids[0]])
    assert result["ok"] is True
    assert result["kept_activity_id"] == ids[0]
    assert result["merged_activity_id"] == ids[1]


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
