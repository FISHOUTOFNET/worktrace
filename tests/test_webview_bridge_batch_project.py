"""Tests for the Timeline batch project editing bridge method.

Covers ``WebViewBridge.batch_update_timeline_activities_project``:

- successful batch update through the bridge → worktrace.api path;
- invalid input (non-list, fewer than two, bool id, non-int, non-positive)
  returns ``{"ok": false, "error": ...}`` with clear Chinese messages;
- batch_too_large returns the ``一次最多修改 100 条活动`` message;
- invalid_project returns the ``请选择有效的项目`` message;
- in_progress activity returns the ``进行中记录无法批量修改`` message;
- hidden_activity returns the ``隐藏记录无法批量修改`` message;
- operation_failed returns the generic ``操作失败`` message;
- unknown error codes collapse to ``操作失败``;
- bool project_id is rejected;
- error results do not contain tracebacks, SQL errors, file paths,
  window titles, or clipboard data;
- the bridge does not import backend internals (services/db/collector/
  runtime/security/config).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from worktrace.api.timeline_api import TimelineBatchProjectError
from worktrace.db import get_connection
from worktrace.services import activity_service, project_service, settings_service
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


def _seed_closed_status_activity(status="idle", start="09:30:00", end="10:00:00", day="2026-06-25"):
    aid = activity_service.create_activity(
        status.title(),
        status,
        f"{status} status",
        status=status,
        start_time=f"{day} {start}",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} {end}")
    return aid


def _seed_two_closed_activities():
    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    a2 = _seed_closed_activity(start="09:30:00", end="10:00:00")
    return [a1, a2]




def test_batch_success(bridge):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, project)
    assert result["ok"] is True
    assert result["updated_count"] == 2


def test_batch_success_is_json_serializable(bridge):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, project)
    json.dumps(result)


def test_batch_success_has_no_sensitive_keys(bridge):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, project)
    _assert_no_sensitive_keys(result)




def test_batch_non_list_activity_ids(bridge):
    result = bridge.batch_update_timeline_activities_project("not a list", 1)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_bool_activity_ids(bridge):
    result = bridge.batch_update_timeline_activities_project(True, 1)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_empty_list(bridge):
    result = bridge.batch_update_timeline_activities_project([], 1)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_single_activity(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_project([aid], 1)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_bool_id_in_list(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_project([aid, True], 1)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_non_positive_id(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_project([aid, 0], 1)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_non_int_id_in_list(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_project([aid, "abc"], 1)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_duplicate_ids_deduped(bridge):
    """Duplicate ids that resolve to one id must fail (< 2)."""
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_project([aid, aid], 1)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"




def test_batch_too_large(bridge):
    """More than 100 ids after dedup must fail."""
    result = bridge.batch_update_timeline_activities_project(
        list(range(1, 102)), 1
    )
    assert result["ok"] is False
    assert result["error"] == "一次最多修改 100 条活动"




def test_batch_bool_project_id(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, True)
    assert result["ok"] is False
    assert result["error"] == "请选择有效的项目"


def test_batch_non_positive_project_id(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, 0)
    assert result["ok"] is False
    assert result["error"] == "请选择有效的项目"


def test_batch_non_int_project_id(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, "abc")
    assert result["ok"] is False
    assert result["error"] == "请选择有效的项目"


def test_batch_nonexistent_project(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, 999999)
    assert result["ok"] is False
    assert result["error"] == "请选择有效的项目"


def test_batch_archived_project(bridge):
    project = project_service.create_project("ArchivedProject")
    project_service.archive_project(project)
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, project)
    assert result["ok"] is False
    assert result["error"] == "请选择有效的项目"


def test_batch_disabled_project(bridge):
    project = project_service.create_project("DisabledProject")
    project_service.set_project_enabled(project, False)
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_project(ids, project)
    assert result["ok"] is False
    assert result["error"] == "请选择有效的项目"




def test_batch_nonexistent_activity(bridge):
    project = project_service.create_project("TestProject")
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_project(
        [aid, 999999], project
    )
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_deleted_activity(bridge):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.soft_delete_activity(ids[1])
    result = bridge.batch_update_timeline_activities_project(ids, project)
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_hidden_activity(bridge):
    project = project_service.create_project("TestProject")
    ids = _seed_two_closed_activities()
    activity_service.hide_activity(ids[1])
    result = bridge.batch_update_timeline_activities_project(ids, project)
    assert result["ok"] is False
    assert result["error"] == "隐藏记录无法批量修改"


def test_batch_in_progress_activity(bridge):
    project = project_service.create_project("TestProject")
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    result = bridge.batch_update_timeline_activities_project([a1, a2], project)
    assert result["ok"] is False
    assert result["error"] == "进行中记录无法批量修改"


def test_batch_system_status_activity_returns_contract_message(bridge):
    project = project_service.create_project("TestProject")
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = _seed_closed_status_activity("idle")

    result = bridge.batch_update_timeline_activities_project([a1, a2], project)

    assert result == {"ok": False, "error": "系统状态记录不支持项目编辑"}




def test_batch_operation_failed_returns_generic(bridge):
    """When the API raises ``TimelineBatchProjectError("operation_failed")``,
    the bridge must return the generic ``操作失败`` message."""
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_project",
        side_effect=TimelineBatchProjectError("operation_failed"),
    ):
        result = bridge.batch_update_timeline_activities_project(ids, 1)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "operation_failed" not in str(result)


def test_batch_unknown_error_code_returns_generic(bridge):
    """Unknown error codes must collapse to ``操作失败``."""
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_project",
        side_effect=TimelineBatchProjectError("unknown_code"),
    ):
        result = bridge.batch_update_timeline_activities_project(ids, 1)
    assert result["ok"] is False
    assert result["error"] == "操作失败"




def test_batch_no_traceback_on_error(bridge):
    """Unexpected exceptions must collapse to the generic message."""
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_project",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.batch_update_timeline_activities_project(ids, 1)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_batch_error_has_no_sensitive_keys(bridge):
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_project",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.batch_update_timeline_activities_project(ids, 1)
    _assert_no_sensitive_keys(result)




def test_bridge_does_not_import_backend_internals():
    """The bridge module must not import services / db / collector /
    security / runtime / config. Only worktrace.api and worktrace.formatters
    are allowed."""
    bridge_src = (
        __import__("worktrace.webview_ui.bridge", fromlist=["bridge"]).__file__
    )
    with open(bridge_src, "r", encoding="utf-8") as f:
        source = f.read()
    for forbidden in (
        "import worktrace.services",
        "import worktrace.db",
        "import worktrace.collector",
        "import worktrace.security",
        "import worktrace.runtime",
        "import worktrace.config",
        "from worktrace.services",
        "from worktrace.db",
        "from worktrace.collector",
        "from worktrace.security",
        "from worktrace.runtime",
        "from worktrace.config",
    ):
        assert forbidden not in source, (
            "bridge must not import " + forbidden
        )
