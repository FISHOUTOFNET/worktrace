"""Tests for the Phase 3B.7 Timeline batch note editing bridge method.

Covers ``WebViewBridge.batch_update_timeline_activities_note``:

- successful batch update through the bridge -> worktrace.api path;
- invalid input (non-list, fewer than two, bool id, non-int, non-positive)
  returns ``{"ok": false, "error": ...}`` with clear Chinese messages;
- batch_too_large returns the ``一次最多修改 100 条活动`` message;
- invalid_note returns the ``请输入有效备注`` message;
- note_too_long returns the ``备注过长`` message;
- in_progress activity returns the ``进行中记录无法批量修改`` message;
- hidden_activity returns the ``隐藏记录无法批量修改`` message;
- operation_failed returns the generic ``操作失败`` message;
- unknown error codes collapse to ``操作失败``;
- bool / None note is rejected;
- empty note is allowed and clears notes;
- error results do not contain tracebacks, SQL errors, file paths,
  window titles, clipboard data, old note, or new note content;
- the bridge does not import backend internals (services/db/collector/
  runtime/security/config).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from worktrace.api.timeline_api import TimelineBatchNoteError
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
    "old_note",
    "new_note",
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


def _seed_two_closed_activities():
    a1 = _seed_closed_activity(start="09:00:00", end="09:30:00")
    a2 = _seed_closed_activity(start="09:30:00", end="10:00:00")
    return [a1, a2]


def _get_activity_note(activity_id: int) -> str | None:
    from worktrace.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT note FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    return row["note"] if row else None


# --- batch_update_timeline_activities_note: success ----------------------


def test_batch_success(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_note(ids, "new note")
    assert result["ok"] is True
    assert result["updated_count"] == 2
    for aid in ids:
        assert _get_activity_note(aid) == "new note"


def test_batch_success_is_json_serializable(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_note(ids, "note")
    json.dumps(result)


def test_batch_success_has_no_sensitive_keys(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_note(ids, "note")
    _assert_no_sensitive_keys(result)


def test_batch_empty_note_clears(bridge):
    """An empty string note must clear all selected activities' notes."""
    a1 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx",
        start_time="2026-06-25 09:00:00", note="old 1",
    )
    activity_service.finalize_created_activity(a1)
    activity_service.close_activity(a1, "2026-06-25 09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A2.docx",
        start_time="2026-06-25 09:30:00", note="old 2",
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_activity(a2, "2026-06-25 10:00:00")
    result = bridge.batch_update_timeline_activities_note([a1, a2], "")
    assert result["ok"] is True
    assert result["updated_count"] == 2
    assert _get_activity_note(a1) == ""
    assert _get_activity_note(a2) == ""


# --- batch_update_timeline_activities_note: invalid selection ------------


def test_batch_non_list_activity_ids(bridge):
    result = bridge.batch_update_timeline_activities_note("not a list", "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_bool_activity_ids(bridge):
    result = bridge.batch_update_timeline_activities_note(True, "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_empty_list(bridge):
    result = bridge.batch_update_timeline_activities_note([], "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_single_activity(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_note([aid], "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_bool_id_in_list(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_note([aid, True], "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_non_positive_id(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_note([aid, 0], "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_non_int_id_in_list(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_note([aid, "abc"], "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_duplicate_ids_deduped(bridge):
    """Duplicate ids that resolve to one id must fail (< 2)."""
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_note([aid, aid], "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


# --- batch_update_timeline_activities_note: batch_too_large --------------


def test_batch_too_large(bridge):
    """More than 100 ids after dedup must fail."""
    result = bridge.batch_update_timeline_activities_note(
        list(range(1, 102)), "note"
    )
    assert result["ok"] is False
    assert result["error"] == "一次最多修改 100 条活动"


# --- batch_update_timeline_activities_note: invalid_note / note_too_long --


def test_batch_note_none(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_note(ids, None)
    assert result["ok"] is False
    assert result["error"] == "请输入有效备注"


def test_batch_note_non_str(bridge):
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_note(ids, 123)
    assert result["ok"] is False
    assert result["error"] == "请输入有效备注"


def test_batch_note_too_long(bridge):
    ids = _seed_two_closed_activities()
    long_note = "x" * 2001
    result = bridge.batch_update_timeline_activities_note(ids, long_note)
    assert result["ok"] is False
    assert result["error"] == "备注过长"


# --- batch_update_timeline_activities_note: activity states --------------


def test_batch_nonexistent_activity(bridge):
    aid = _seed_closed_activity()
    result = bridge.batch_update_timeline_activities_note(
        [aid, 999999], "note"
    )
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_deleted_activity(bridge):
    ids = _seed_two_closed_activities()
    activity_service.soft_delete_activity(ids[1])
    result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is False
    assert result["error"] == "请选择至少两个活动"


def test_batch_hidden_activity(bridge):
    ids = _seed_two_closed_activities()
    activity_service.hide_activity(ids[1])
    result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is False
    assert result["error"] == "隐藏记录无法批量修改"


def test_batch_in_progress_activity(bridge):
    a1 = _seed_closed_activity(end="09:30:00")
    a2 = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:30:00"
    )
    activity_service.finalize_created_activity(a2)
    result = bridge.batch_update_timeline_activities_note([a1, a2], "note")
    assert result["ok"] is False
    assert result["error"] == "进行中记录无法批量修改"


# --- batch_update_timeline_activities_note: operation_failed -------------


def test_batch_operation_failed_returns_generic(bridge):
    """When the API raises ``TimelineBatchNoteError("operation_failed")``,
    the bridge must return the generic ``操作失败`` message."""
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_note",
        side_effect=TimelineBatchNoteError("operation_failed"),
    ):
        result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "operation_failed" not in str(result)


def test_batch_unknown_error_code_returns_generic(bridge):
    """Unknown error codes must collapse to ``操作失败``."""
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_note",
        side_effect=TimelineBatchNoteError("unknown_code"),
    ):
        result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is False
    assert result["error"] == "操作失败"


# --- batch_update_timeline_activities_note: privacy / safety -------------


def test_batch_no_traceback_on_error(bridge):
    """Unexpected exceptions must collapse to the generic message."""
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_note",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_batch_error_has_no_sensitive_keys(bridge):
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_note",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.batch_update_timeline_activities_note(ids, "note")
    _assert_no_sensitive_keys(result)


def test_batch_success_does_not_leak_note_content(bridge):
    """The success result must not include the note content (old or new)."""
    ids = _seed_two_closed_activities()
    secret_note = "super_secret_note_content"
    result = bridge.batch_update_timeline_activities_note(ids, secret_note)
    assert result["ok"] is True
    # The note content must not appear anywhere in the result payload.
    assert secret_note not in str(result)
    assert "note" not in result
    assert "old_note" not in result
    assert "new_note" not in result


# --- bridge import boundary -----------------------------------------------


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


# --- Phase 3B.7.1: bridge hardening --------------------------------------
#
# These tests verify the bridge error/success payload does not leak note
# content, the updated_count matches the selection, and the bridge
# converges all error paths to stable Chinese messages.


def test_batch_error_does_not_leak_note_content(bridge):
    """Phase 3B.7.1: error payloads must not contain the note content that
    was sent to the bridge. The user may have typed sensitive content into
    the note textarea; a validation error must not echo it back."""
    ids = _seed_two_closed_activities()
    secret_note = "super_secret_note_in_error_path"
    # Trigger an error (in_progress) while sending a secret note.
    a3 = activity_service.create_activity(
        "Word", "winword.exe", "A3.docx", start_time="2026-06-25 11:00:00"
    )
    activity_service.finalize_created_activity(a3)
    # a3 is in-progress (no close_activity call).
    result = bridge.batch_update_timeline_activities_note(
        [ids[0], a3], secret_note
    )
    assert result["ok"] is False
    # The note content must not appear anywhere in the error payload.
    assert secret_note not in str(result)
    assert "note" not in result
    assert "old_note" not in result
    assert "new_note" not in result


def test_batch_success_updated_count_matches_selection(bridge):
    """Phase 3B.7.1: the ``updated_count`` in the success payload must
    equal the number of activities sent (after dedup)."""
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is True
    assert result["updated_count"] == len(ids)


def test_batch_success_updated_count_matches_deduped_selection(bridge):
    """Phase 3B.7.1: duplicate ids in the input must be deduplicated, and
    ``updated_count`` must reflect the deduplicated count."""
    ids = _seed_two_closed_activities()
    # Send duplicates.
    result = bridge.batch_update_timeline_activities_note(
        [ids[0], ids[1], ids[0], ids[1]], "note"
    )
    assert result["ok"] is True
    assert result["updated_count"] == 2


def test_batch_all_chinese_error_messages_present(bridge):
    """Phase 3B.7.1: verify every stable error code produces its exact
    Chinese message through the bridge. This guards against accidental
    message drift."""
    ids = _seed_two_closed_activities()
    cases = [
        ("invalid_selection", "请选择至少两个活动"),
        ("batch_too_large", "一次最多修改 100 条活动"),
        ("invalid_note", "请输入有效备注"),
        ("note_too_long", "备注过长"),
        ("in_progress", "进行中记录无法批量修改"),
        ("hidden_activity", "隐藏记录无法批量修改"),
        ("operation_failed", "操作失败"),
    ]
    for code, expected_msg in cases:
        with patch(
            "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_note",
            side_effect=TimelineBatchNoteError(code),
        ):
            result = bridge.batch_update_timeline_activities_note(ids, "note")
        assert result["ok"] is False
        assert result["error"] == expected_msg, (
            f"error code '{code}' must produce '{expected_msg}', "
            f"got '{result['error']}'"
        )


def test_batch_unknown_code_converges_to_generic(bridge):
    """Phase 3B.7.1: an unrecognized error code must converge to
    ``操作失败`` so internal details are never surfaced."""
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_note",
        side_effect=TimelineBatchNoteError("unexpected_new_code_xyz"),
    ):
        result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "unexpected_new_code_xyz" not in str(result)


def test_batch_success_payload_has_only_ok_and_count(bridge):
    """Phase 3B.7.1: the success payload must contain exactly ``ok`` and
    ``updated_count`` — no extra keys that could leak internal data."""
    ids = _seed_two_closed_activities()
    result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is True
    assert set(result.keys()) == {"ok", "updated_count"}


def test_batch_error_payload_has_only_ok_and_error(bridge):
    """Phase 3B.7.1: the error payload must contain exactly ``ok`` and
    ``error`` — no extra keys that could leak internal data."""
    ids = _seed_two_closed_activities()
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.batch_update_timeline_activities_note",
        side_effect=TimelineBatchNoteError("operation_failed"),
    ):
        result = bridge.batch_update_timeline_activities_note(ids, "note")
    assert result["ok"] is False
    assert set(result.keys()) == {"ok", "error"}


def test_batch_note_too_long_rejected_at_bridge(bridge):
    """Phase 3B.7.1: the bridge must reject an overly long note before
    calling the API, returning the ``备注过长`` message."""
    ids = _seed_two_closed_activities()
    from worktrace.api import timeline_api as api_module

    long_note = "x" * (api_module.TIMELINE_NOTE_MAX_LENGTH + 1)
    result = bridge.batch_update_timeline_activities_note(ids, long_note)
    assert result["ok"] is False
    assert result["error"] == "备注过长"
