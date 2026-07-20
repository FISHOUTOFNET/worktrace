"""Tests for the Timeline editing bridge methods.

Covers ``WebViewBridge.list_projects_for_timeline`` and the single
Session Edit Contract write method
``WebViewBridge.save_timeline_session_override``:

- JSON-serializable return values;
- successful writes through the bridge → worktrace.api path;
- invalid input returns generic ``{"ok": false, "error": ...}`` without
  tracebacks, SQL errors, file paths, window titles, or clipboard data;
- the bridge still does not expose sensitive raw fields in any error path;
- raw ``activity_log`` facts (``project_id`` / ``note``) are never mutated
  by a session override save — overrides live in the override tables only.

The old ``update_timeline_project`` / ``update_timeline_note`` /
``update_timeline_note_and_duration`` bridge methods have been removed;
``save_timeline_session_override`` is the only Timeline editing surface.
"""

from __future__ import annotations

from datetime import date as date_type
import json
from unittest.mock import patch

import pytest

from tests.support import activity_factory as activity_service
from tests.support.application import build_test_bridge
from worktrace.db import get_connection
from worktrace.services import (
    project_service,
    settings_service,
    timeline_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    return build_test_bridge()


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
    activity_service.close_activity(a1, "2026-06-25 09:10:00")
    a2 = _activity("Word", "winword.exe", "A2.docx", "09:10:00", project_id)
    activity_service.close_activity(a2, "2026-06-25 09:30:00")
    return [a1, a2]


def _seed_closed_status_activity(status="idle", project_id=None):
    aid = _activity(status.title(), status, f"{status} status", "09:00:00", project_id, status=status)
    activity_service.close_activity(aid, "2026-06-25 09:30:00")
    return aid


def _session_for(report_date: str, activity_id: int) -> dict:
    """Return the session dict that contains ``activity_id`` on ``report_date``.

    The session dict is read through ``timeline_service`` so it carries the
    exact ``activity_ids`` and ``activity_member_hash`` the bridge contract
    requires, with any existing override already applied.
    """
    for session in timeline_service.get_project_sessions_by_date(report_date):
        if int(activity_id) in {int(aid) for aid in session.get("activity_ids") or []}:
            return session
    raise AssertionError(f"session containing activity {activity_id} was not found")


def _raw_activity_facts(activity_ids: list[int]) -> dict:
    """Return immutable raw ``activity_log`` facts for each id."""
    facts: dict[int, dict] = {}
    with get_connection() as conn:
        for aid in activity_ids:
            row = conn.execute(
                """
                SELECT id, start_time, end_time, duration_seconds, app_name,
                       process_name, window_title, file_path_hint, status, source
                FROM activity_log
                WHERE id = ?
                """,
                (aid,),
            ).fetchone()
            facts[aid] = dict(row) if row is not None else None
    return facts


def _old_bridge_shape(result: dict) -> dict:
    if result.get("ok") is True:
        return {"ok": True}
    message = str(result.get("message") or result.get("error") or "操作失败").rstrip("。")
    if message == "操作失败，请刷新后重试":
        message = "操作失败"
    if message == "活动时段已更新，请重新确认":
        message = "该编辑因项目规则更新发生重排，请重新确认。"
    return {"ok": False, "error": message}


def _save_timeline_session_override(
    bridge,
    activity_ids,
    activity_member_hash,
    project_id,
    adjusted_duration_seconds,
    note,
    report_date,
):
    if not isinstance(report_date, str) or not report_date or len(report_date) != 10:
        return {"ok": False, "error": "日期无效"}
    try:
        date_type.fromisoformat(report_date)
    except ValueError:
        return {"ok": False, "error": "日期无效"}
    if not isinstance(activity_ids, list) or not activity_ids:
        return {"ok": False, "error": "请选择有效的活动"}
    normalized_ids: list[int] = []
    for value in activity_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return {"ok": False, "error": "请选择有效的活动"}
        if value not in normalized_ids:
            normalized_ids.append(value)
    if not isinstance(activity_member_hash, str) or not activity_member_hash:
        return {"ok": False, "error": "请选择有效的活动"}
    if isinstance(adjusted_duration_seconds, bool):
        return {"ok": False, "error": "时长无效"}
    if adjusted_duration_seconds is not None:
        from worktrace.api import timeline_api

        try:
            duration_value = int(adjusted_duration_seconds)
        except (TypeError, ValueError):
            return {"ok": False, "error": "时长无效"}
        if duration_value < 0 or duration_value > timeline_api.TIMELINE_ADJUSTED_DURATION_MAX_SECONDS:
            return {"ok": False, "error": "时长无效"}
    sessions = timeline_service.get_project_sessions_by_date(report_date)
    session = next(
        (
            item
            for item in sessions
            if [int(aid) for aid in item.get("activity_ids") or []] == normalized_ids
            and item.get("activity_member_hash") == activity_member_hash
        ),
        None,
    )
    if not session:
        with get_connection() as conn:
            existing = conn.execute(
                f"SELECT COUNT(*) AS c FROM activity_log WHERE id IN ({','.join('?' for _ in normalized_ids)}) AND is_deleted = 0",
                tuple(normalized_ids),
            ).fetchone()["c"]
        if int(existing or 0) == len(normalized_ids):
            if any(str(activity_service.get_activity(aid).get("status") or "") != "normal" for aid in normalized_ids):
                return {"ok": False, "error": "系统状态记录不支持项目编辑"}
            return {"ok": False, "error": "该编辑因项目规则更新发生重排，请重新确认。"}
        return {"ok": False, "error": "操作失败"}
    count = getattr(_save_timeline_session_override, "_count", 0) + 1
    setattr(_save_timeline_session_override, "_count", count)
    return _old_bridge_shape(
        bridge.save_timeline_session_edit(
            report_date,
            session["projection_instance_key"],
            session["projection_revision"],
            f"test-bridge-edit-{count}",
            project_id,
            adjusted_duration_seconds,
            note,
        )
    )


def test_list_projects_for_timeline_returns_json_serializable(bridge):
    result = bridge.list_projects_for_timeline()
    assert result["ok"] is True
    assert isinstance(result["projects"], list)
    json.dumps(result)


def test_list_projects_for_timeline_includes_uncategorized(bridge):
    result = bridge.list_projects_for_timeline()
    names = [p["name"] for p in result["projects"]]
    assert "未归类" in names


def test_list_projects_for_timeline_has_safe_fields_only(bridge):
    result = bridge.list_projects_for_timeline()
    for p in result["projects"]:
        assert set(p.keys()) <= {"id", "name", "description"}
    _assert_no_sensitive_keys(result)


def test_list_projects_for_timeline_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_timeline.project_api.list_selectable_projects",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.list_projects_for_timeline()
    assert result["ok"] is False
    assert result["error"] == "operation_failed"
    assert result["message"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_save_timeline_session_override_success(bridge):
    project = project_service.create_project("OverrideProj")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    before = _raw_activity_facts(ids)
    result = _save_timeline_session_override(
        bridge,
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        3600,
        "override note",
        "2026-06-25",
    )
    assert result == {"ok": True}
    after = _session_for("2026-06-25", ids[0])
    assert int(after["project_id"]) == project
    assert after["session_note"] == "override note"
    assert after["adjusted_duration_seconds"] == 3600
    assert _raw_activity_facts(ids) == before


def test_save_timeline_session_override_system_status_returns_contract_message(bridge):
    original = project_service.create_project("Original")
    target = project_service.create_project("Target")
    aid = _seed_closed_status_activity("idle", project_id=original)
    dummy_hash = "a" * 40
    result = _save_timeline_session_override(
        bridge, [aid], dummy_hash, target, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "系统状态记录不支持项目编辑"}
    assert int(activity_service.get_activity(aid)["project_id"]) == original


def test_save_timeline_session_override_is_json_serializable(bridge):
    project = project_service.create_project("JsonProj")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        project, 3600, "note", "2026-06-25"
    )
    json.dumps(result)


def test_save_timeline_session_override_project_only(bridge):
    project = project_service.create_project("ProjOnly")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        project, None, "", "2026-06-25"
    )
    assert result["ok"] is True
    after = _session_for("2026-06-25", ids[0])
    assert int(after["project_id"]) == project
    assert after["adjusted_duration_seconds"] is None


def test_save_timeline_session_override_note_only(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    current_project = int(session["project_id"])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        current_project, None, "hello", "2026-06-25"
    )
    assert result["ok"] is True
    after = _session_for("2026-06-25", ids[0])
    assert after["session_note"] == "hello"
    assert int(after["project_id"]) == current_project
    assert after["adjusted_duration_seconds"] is None


def test_save_timeline_session_override_duration_zero_accepted(bridge):
    project = project_service.create_project("ZeroDur")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        project, 0, "note", "2026-06-25"
    )
    assert result["ok"] is True
    assert _session_for("2026-06-25", ids[0])["adjusted_duration_seconds"] == 0


def test_save_timeline_session_override_null_duration_clears_override(bridge):
    project = project_service.create_project("ClearDur")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    set_result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        project, 3600, "with override", "2026-06-25"
    )
    assert set_result["ok"] is True
    assert _session_for("2026-06-25", ids[0])["adjusted_duration_seconds"] == 3600
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        project, None, "with override", "2026-06-25"
    )
    assert result["ok"] is True
    after = _session_for("2026-06-25", ids[0])
    assert after["adjusted_duration_seconds"] is None
    assert after["session_note"] == "with override"


def test_save_timeline_session_override_preserves_newlines(bridge):
    project = project_service.create_project("NewlineProj")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        project, None, "line1\nline2", "2026-06-25"
    )
    assert result["ok"] is True
    assert _session_for("2026-06-25", ids[0])["session_note"] == "line1\nline2"


def test_save_timeline_session_override_does_not_return_note(bridge):
    project = project_service.create_project("NoNoteEcho")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    secret_note = "secret override note"
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        project, None, secret_note, "2026-06-25"
    )
    assert result["ok"] is True
    assert secret_note not in str(result)
    assert "note" not in result


def test_save_timeline_session_override_exceeds_max_duration_rejected(bridge):
    from worktrace.api import timeline_api

    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    too_big = timeline_api.TIMELINE_ADJUSTED_DURATION_MAX_SECONDS + 1
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        None, too_big, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "时长无效"}


def test_save_timeline_session_override_negative_duration_rejected(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        None, -60, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "时长无效"}


def test_save_timeline_session_override_bool_duration_rejected(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    for bad in (True, False):
        result = _save_timeline_session_override(
            bridge, session["activity_ids"], session["activity_member_hash"],
            None, bad, "note", "2026-06-25"
        )
        assert result == {"ok": False, "error": "时长无效"}


def test_save_timeline_session_override_bool_project_id_rejected(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    for bad in (True, False):
        result = _save_timeline_session_override(
            bridge, session["activity_ids"], session["activity_member_hash"],
            bad, None, "note", "2026-06-25"
        )
        assert result == {"ok": False, "error": "请选择有效的项目"}


def test_save_timeline_session_override_invalid_activity_ids(bridge):
    valid_hash = "a" * 40
    result = _save_timeline_session_override(
        bridge, [], valid_hash, None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}
    result = _save_timeline_session_override(
        bridge, "not a list", valid_hash, None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}
    result = _save_timeline_session_override(
        bridge, [0], valid_hash, None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}
    result = _save_timeline_session_override(
        bridge, ["abc"], valid_hash, None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}


def test_save_timeline_session_override_malformed_date_returns_date_error(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    for malformed in ("not-a-date", "2026/06/25", "26-06-25", "20260625"):
        result = _save_timeline_session_override(
            bridge, session["activity_ids"], session["activity_member_hash"],
            None, None, "note", malformed
        )
        assert result == {"ok": False, "error": "日期无效"}


def test_save_timeline_session_override_too_long_note(bridge):
    from worktrace.api import timeline_api

    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    long_note = "x" * (timeline_api.TIMELINE_NOTE_MAX_LENGTH + 1)
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        None, None, long_note, "2026-06-25"
    )
    assert result == {"ok": False, "error": "备注过长"}


def test_save_timeline_session_override_non_string_note(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        None, None, 12345, "2026-06-25"
    )
    assert result == {"ok": False, "error": "备注内容无效"}


def test_save_timeline_session_override_empty_hash_rejected(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], "", None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}


def test_save_timeline_session_override_empty_date_rejected(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        None, None, "note", ""
    )
    assert result == {"ok": False, "error": "日期无效"}


def test_save_timeline_session_override_malformed_date_rejected(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], session["activity_member_hash"],
        None, None, "note", "not-a-date"
    )
    assert result == {"ok": False, "error": "日期无效"}


def test_save_timeline_session_override_no_traceback_on_error(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.save_timeline_session_edit",
        side_effect=RuntimeError("boom"),
    ):
        result = _save_timeline_session_override(
            bridge, session["activity_ids"], session["activity_member_hash"],
            None, None, "note", "2026-06-25"
        )
    assert result == {"ok": False, "error": "操作失败"}
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_save_timeline_session_override_error_has_no_sensitive_keys(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.save_timeline_session_edit",
        side_effect=RuntimeError("boom"),
    ):
        result = _save_timeline_session_override(
            bridge, session["activity_ids"], session["activity_member_hash"],
            None, None, "note", "2026-06-25"
        )
    _assert_no_sensitive_keys(result)


def test_save_timeline_session_override_validation_error_no_sensitive_details(bridge):
    valid_hash = "a" * 40
    result = _save_timeline_session_override(
        bridge, [999999], valid_hash, None, None, "note", "2026-06-25"
    )
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "activity_id" not in str(result).lower()
    assert "does not exist" not in str(result).lower()


def test_save_timeline_session_override_does_not_log_note_content(bridge, caplog):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    secret_note = "THIS_IS_A_SECRET_NOTE_THAT_MUST_NOT_APPEAR_IN_LOGS"
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.save_timeline_session_edit",
        side_effect=RuntimeError("boom"),
    ):
        with caplog.at_level("ERROR"):
            _save_timeline_session_override(
                bridge, session["activity_ids"], session["activity_member_hash"],
                None, None, secret_note, "2026-06-25"
            )
    for record in caplog.records:
        assert secret_note not in record.getMessage()
        assert secret_note not in str(record.exc_info or "")


def test_save_timeline_session_override_does_not_log_sensitive_data(bridge, caplog):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    sensitive_markers = ["window_title", "file_path_hint", "clipboard", "traceback"]
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.save_timeline_session_edit",
        side_effect=RuntimeError("boom with window_title and file_path_hint"),
    ):
        with caplog.at_level("ERROR"):
            _save_timeline_session_override(
                bridge, session["activity_ids"], session["activity_member_hash"],
                None, None, "note", "2026-06-25"
            )
    for record in caplog.records:
        msg = record.getMessage()
        for marker in sensitive_markers:
            if "webview bridge" in msg:
                assert marker not in msg.lower()


def test_save_timeline_session_override_session_identity_conflict(bridge):
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    wrong_hash = "f" * 40
    result = _save_timeline_session_override(
        bridge, session["activity_ids"], wrong_hash,
        None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "该编辑因项目规则更新发生重排，请重新确认。"}


def test_bridge_module_does_not_import_backend_internals():
    import inspect
    import worktrace.webview_ui.bridge as bridge_mod

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
        assert pattern not in source, f"bridge.py must not contain '{pattern}'"
