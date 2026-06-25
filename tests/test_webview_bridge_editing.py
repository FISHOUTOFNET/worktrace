"""Tests for the Phase 3A Timeline editing bridge methods.

Covers ``WebViewBridge.list_projects_for_timeline``,
``WebViewBridge.update_timeline_project``, and
``WebViewBridge.update_timeline_note``:

- JSON-serializable return values;
- successful writes through the bridge → worktrace.api path;
- invalid input returns generic ``{"ok": false, "error": ...}`` without
  tracebacks, SQL errors, file paths, window titles, or clipboard data;
- the bridge still does not expose sensitive raw fields in any error path.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

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


def _activity(app, process, title, start, project_id=None, status="normal"):
    aid = activity_service.create_activity(
        app,
        process,
        title,
        start_time=f"2026-06-25 {start}",
        project_id=project_id,
        status=status,
    )
    activity_service.finalize_created_activity(aid)
    return aid


def _seed_session(project_id=None):
    a1 = _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_id)
    a2 = _activity("Word", "winword.exe", "A2.docx", "09:10:00", project_id)
    activity_service.close_activity(a2, "2026-06-25 09:30:00")
    return [a1, a2]


# --- list_projects_for_timeline ------------------------------------------


def test_list_projects_for_timeline_returns_json_serializable(bridge):
    result = bridge.list_projects_for_timeline()
    assert result["ok"] is True
    assert isinstance(result["projects"], list)
    json.dumps(result)


def test_list_projects_for_timeline_includes_uncategorized(bridge):
    """The uncategorized system project must be in the list so the frontend
    can represent 'uncategorized' without a sentinel."""
    result = bridge.list_projects_for_timeline()
    names = [p["name"] for p in result["projects"]]
    assert "未归类" in names


def test_list_projects_for_timeline_has_safe_fields_only(bridge):
    """Each project must only expose id/name/description — no sensitive
    fields."""
    result = bridge.list_projects_for_timeline()
    for p in result["projects"]:
        assert set(p.keys()) <= {"id", "name", "description"}
    _assert_no_sensitive_keys(result)


def test_list_projects_for_timeline_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge.project_api.list_selectable_projects",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.list_projects_for_timeline()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


# --- update_timeline_project ---------------------------------------------


def test_update_timeline_project_success(bridge):
    project = project_service.create_project("BridgeProject")
    ids = _seed_session()
    result = bridge.update_timeline_project(ids, project)
    assert result["ok"] is True
    # Verify the write happened
    for aid in ids:
        activity = activity_service.get_activity(aid)
        assert int(activity["project_id"]) == project


def test_update_timeline_project_is_json_serializable(bridge):
    project = project_service.create_project("SerProj")
    ids = _seed_session()
    result = bridge.update_timeline_project(ids, project)
    json.dumps(result)


def test_update_timeline_project_invalid_activity_ids(bridge):
    project = project_service.create_project("P")
    # Empty list
    result = bridge.update_timeline_project([], project)
    assert result["ok"] is False
    assert "error" in result
    # Non-list
    result = bridge.update_timeline_project("not a list", project)
    assert result["ok"] is False
    # List with non-int
    result = bridge.update_timeline_project(["abc"], project)
    assert result["ok"] is False
    # List with zero/negative
    result = bridge.update_timeline_project([0, -1], project)
    assert result["ok"] is False


def test_update_timeline_project_invalid_project_id(bridge):
    ids = _seed_session()
    # Non-int
    result = bridge.update_timeline_project(ids, "abc")
    assert result["ok"] is False
    # Nonexistent
    result = bridge.update_timeline_project(ids, 999999)
    assert result["ok"] is False


def test_update_timeline_project_no_traceback_on_error(bridge):
    ids = _seed_session()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.reclassify_timeline_session_project",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.update_timeline_project(ids, 1)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_update_timeline_project_error_has_no_sensitive_keys(bridge):
    """Error results must not leak sensitive raw fields at any level."""
    ids = _seed_session()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.reclassify_timeline_session_project",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.update_timeline_project(ids, 1)
    _assert_no_sensitive_keys(result)


def test_update_timeline_project_validation_error_no_sensitive_details(bridge):
    """When ValueError is raised by the API (e.g. nonexistent activity),
    the bridge must return a generic error without echoing the underlying
    ValueError text."""
    project = project_service.create_project("ValProj")
    result = bridge.update_timeline_project([999999], project)
    assert result["ok"] is False
    # The error must be generic, not the ValueError text
    assert result["error"] == "操作失败"
    assert "activity_id" not in str(result).lower()
    assert "does not exist" not in str(result).lower()


# --- update_timeline_note ------------------------------------------------


def test_update_timeline_note_success(bridge):
    ids = _seed_session()
    result = bridge.update_timeline_note(ids, "bridge note", "2026-06-25")
    assert result["ok"] is True
    # Verify the note was written
    from worktrace.services import session_note_service
    note = session_note_service.get_session_note("2026-06-25", ids[0])
    assert note == "bridge note"


def test_update_timeline_note_is_json_serializable(bridge):
    ids = _seed_session()
    result = bridge.update_timeline_note(ids, "note", "2026-06-25")
    json.dumps(result)


def test_update_timeline_note_preserves_newlines(bridge):
    ids = _seed_session()
    result = bridge.update_timeline_note(ids, "line1\nline2", "2026-06-25")
    assert result["ok"] is True
    from worktrace.services import session_note_service
    note = session_note_service.get_session_note("2026-06-25", ids[0])
    assert note == "line1\nline2"


def test_update_timeline_note_invalid_activity_ids(bridge):
    result = bridge.update_timeline_note([], "note", "2026-06-25")
    assert result["ok"] is False
    result = bridge.update_timeline_note("not a list", "note", "2026-06-25")
    assert result["ok"] is False
    result = bridge.update_timeline_note([0], "note", "2026-06-25")
    assert result["ok"] is False


def test_update_timeline_note_non_string_note(bridge):
    ids = _seed_session()
    result = bridge.update_timeline_note(ids, 12345, "2026-06-25")
    assert result["ok"] is False


def test_update_timeline_note_too_long(bridge):
    ids = _seed_session()
    from worktrace.api import timeline_api
    long_note = "x" * (timeline_api.TIMELINE_NOTE_MAX_LENGTH + 1)
    result = bridge.update_timeline_note(ids, long_note, "2026-06-25")
    assert result["ok"] is False
    assert "error" in result


def test_update_timeline_note_invalid_date(bridge):
    ids = _seed_session()
    result = bridge.update_timeline_note(ids, "note", "")
    assert result["ok"] is False
    result = bridge.update_timeline_note(ids, "note", None)
    assert result["ok"] is False


def test_update_timeline_note_no_traceback_on_error(bridge):
    ids = _seed_session()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.update_timeline_session_note",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.update_timeline_note(ids, "note", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_update_timeline_note_error_has_no_sensitive_keys(bridge):
    ids = _seed_session()
    with patch(
        "worktrace.webview_ui.bridge.timeline_api.update_timeline_session_note",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.update_timeline_note(ids, "note", "2026-06-25")
    _assert_no_sensitive_keys(result)


def test_update_timeline_note_validation_error_no_sensitive_details(bridge):
    """When ValueError is raised by the API (e.g. nonexistent activity),
    the bridge must return a generic error without echoing details."""
    result = bridge.update_timeline_note([999999], "note", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "activity_id" not in str(result).lower()
    assert "first_activity_id" not in str(result).lower()


# --- bridge import boundary (regression) ---------------------------------


def test_bridge_module_does_not_import_backend_internals():
    """The bridge must only import worktrace.api, not services/db/collector/
    security. This is also enforced by test_ui_backend_boundary.py but is
    re-asserted here for the Phase 3A editing surface."""
    import worktrace.webview_ui.bridge as bridge_mod
    import inspect

    source = inspect.getsource(bridge_mod)
    forbidden = [
        "from ..services",
        "from worktrace.services",
        "from ..db",
        "from worktrace.db",
        "from ..collector",
        "from worktrace.collector",
        "from ..security",
        "from worktrace.security",
    ]
    for pattern in forbidden:
        assert pattern not in source, (
            f"bridge.py must not contain '{pattern}'"
        )
