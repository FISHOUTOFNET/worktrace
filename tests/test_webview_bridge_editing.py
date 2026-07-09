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

import json
from unittest.mock import patch

import pytest

from worktrace.db import get_connection
from worktrace.services import activity_service, project_service, settings_service, timeline_service
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


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
    """Return raw ``activity_log`` ``project_id``/``note`` for each id.

    Used to prove a session override save never mutates the raw activity
    facts — overrides live in ``project_session_override`` only.
    """
    facts: dict[int, dict] = {}
    with get_connection() as conn:
        for aid in activity_ids:
            row = conn.execute(
                "SELECT project_id, note FROM activity_log WHERE id = ?", (aid,)
            ).fetchone()
            facts[aid] = dict(row) if row is not None else None
    return facts


# ---------------------------------------------------------------------------
# Kept: list_projects_for_timeline (unchanged surface)
# ---------------------------------------------------------------------------


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
        "worktrace.webview_ui.bridge_timeline.project_api.list_selectable_projects",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.list_projects_for_timeline()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


# ---------------------------------------------------------------------------
# save_timeline_session_override — success & shape
# ---------------------------------------------------------------------------


def test_save_timeline_session_override_success(bridge):
    """Saving project + note + duration must succeed, re-read reflects the
    override, and the raw ``activity_log`` facts must be unchanged."""
    project = project_service.create_project("OverrideProj")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])

    before = _raw_activity_facts(ids)

    result = bridge.save_timeline_session_override(
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

    # Raw activity facts must not be mutated by the override save.
    assert _raw_activity_facts(ids) == before


def test_save_timeline_session_override_system_status_returns_contract_message(bridge):
    """A closed status activity (e.g. idle) is not project-editable; the
    bridge must return the contract message and leave the activity's
    effective project unchanged.

    Status activities are not part of any project session, so the member
    hash is not meaningful here — the API's editability check
    (``_ensure_project_editable_for_value_error``) runs *before* session
    resolution and raises ``not_project_activity`` for a status activity
    regardless of the supplied hash. A syntactically valid dummy hash is
    used so the bridge's hash-shape guard passes and the call reaches the
    API layer.
    """
    original = project_service.create_project("Original")
    target = project_service.create_project("Target")
    aid = _seed_closed_status_activity("idle", project_id=original)
    dummy_hash = "a" * 40

    result = bridge.save_timeline_session_override(
        [aid],
        dummy_hash,
        target,
        None,
        "note",
        "2026-06-25",
    )

    assert result == {"ok": False, "error": "系统状态记录不支持项目编辑"}
    assert int(activity_service.get_activity(aid)["project_id"]) == original


def test_save_timeline_session_override_is_json_serializable(bridge):
    project = project_service.create_project("JsonProj")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        3600,
        "note",
        "2026-06-25",
    )
    json.dumps(result)


def test_save_timeline_session_override_project_only(bridge):
    """Saving a project with an empty note and no duration must succeed and
    only change the project."""
    project = project_service.create_project("ProjOnly")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])

    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        None,
        "",
        "2026-06-25",
    )
    assert result["ok"] is True

    after = _session_for("2026-06-25", ids[0])
    assert int(after["project_id"]) == project
    assert after["adjusted_duration_seconds"] is None


def test_save_timeline_session_override_note_only(bridge):
    """A note-only edit must preserve the current project (pass the session's
    current ``project_id``) and write only the note."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    current_project = int(session["project_id"])

    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        current_project,
        None,
        "hello",
        "2026-06-25",
    )
    assert result["ok"] is True

    after = _session_for("2026-06-25", ids[0])
    assert after["session_note"] == "hello"
    assert int(after["project_id"]) == current_project
    assert after["adjusted_duration_seconds"] is None


def test_save_timeline_session_override_duration_zero_accepted(bridge):
    """``0`` is a valid explicit override to zero display/declared duration."""
    project = project_service.create_project("ZeroDur")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])

    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        0,
        "note",
        "2026-06-25",
    )
    assert result["ok"] is True
    assert _session_for("2026-06-25", ids[0])["adjusted_duration_seconds"] == 0


def test_save_timeline_session_override_null_duration_clears_override(bridge):
    """Passing ``None`` for the duration clears an existing duration override
    while preserving the project and note."""
    project = project_service.create_project("ClearDur")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])

    # Set an override first.
    set_result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        3600,
        "with override",
        "2026-06-25",
    )
    assert set_result["ok"] is True
    assert _session_for("2026-06-25", ids[0])["adjusted_duration_seconds"] == 3600

    # Clear the duration with None (keep project + note).
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        None,
        "with override",
        "2026-06-25",
    )
    assert result["ok"] is True
    after = _session_for("2026-06-25", ids[0])
    assert after["adjusted_duration_seconds"] is None
    assert after["session_note"] == "with override"


def test_save_timeline_session_override_preserves_newlines(bridge):
    """Newlines in the note must be preserved verbatim."""
    project = project_service.create_project("NewlineProj")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])

    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        None,
        "line1\nline2",
        "2026-06-25",
    )
    assert result["ok"] is True
    assert _session_for("2026-06-25", ids[0])["session_note"] == "line1\nline2"


def test_save_timeline_session_override_does_not_return_note(bridge):
    """The bridge success result must not echo the note content."""
    project = project_service.create_project("NoNoteEcho")
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])

    secret_note = "secret override note"
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        None,
        secret_note,
        "2026-06-25",
    )
    assert result["ok"] is True
    assert secret_note not in str(result)
    assert "note" not in result


# ---------------------------------------------------------------------------
# save_timeline_session_override — value validation
# ---------------------------------------------------------------------------


def test_save_timeline_session_override_exceeds_max_duration_rejected(bridge):
    """Durations above ``TIMELINE_ADJUSTED_DURATION_MAX_SECONDS`` must be
    rejected with 时长无效."""
    from worktrace.api import timeline_api

    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    too_big = timeline_api.TIMELINE_ADJUSTED_DURATION_MAX_SECONDS + 1
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        None,
        too_big,
        "note",
        "2026-06-25",
    )
    assert result == {"ok": False, "error": "时长无效"}


def test_save_timeline_session_override_negative_duration_rejected(bridge):
    """Negative durations must be rejected with 时长无效."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        None,
        -60,
        "note",
        "2026-06-25",
    )
    assert result == {"ok": False, "error": "时长无效"}


def test_save_timeline_session_override_bool_duration_rejected(bridge):
    """``bool`` must not be coerced to ``1``/``0``; reject with 时长无效."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    for bad in (True, False):
        result = bridge.save_timeline_session_override(
            session["activity_ids"],
            session["activity_member_hash"],
            None,
            bad,
            "note",
            "2026-06-25",
        )
        assert result == {"ok": False, "error": "时长无效"}


def test_save_timeline_session_override_bool_project_id_rejected(bridge):
    """``bool`` must not be coerced to ``1`` for ``project_id``."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    for bad in (True, False):
        result = bridge.save_timeline_session_override(
            session["activity_ids"],
            session["activity_member_hash"],
            bad,
            None,
            "note",
            "2026-06-25",
        )
        assert result == {"ok": False, "error": "请选择有效的项目"}


def test_save_timeline_session_override_invalid_activity_ids(bridge):
    """Invalid ``activity_ids`` shapes must be rejected."""
    valid_hash = "a" * 40
    # Empty list
    result = bridge.save_timeline_session_override(
        [], valid_hash, None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}
    # Non-list
    result = bridge.save_timeline_session_override(
        "not a list", valid_hash, None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}
    # List with zero
    result = bridge.save_timeline_session_override(
        [0], valid_hash, None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}
    # List with non-int
    result = bridge.save_timeline_session_override(
        ["abc"], valid_hash, None, None, "note", "2026-06-25"
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}


def test_save_timeline_session_override_malformed_date_returns_date_error(bridge):
    """A malformed ``report_date`` must return ``"日期无效"`` (not the
    generic ``"操作失败"``) so the user gets a clearer message."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    for malformed in ("not-a-date", "2026/06/25", "26-06-25", "20260625"):
        result = bridge.save_timeline_session_override(
            session["activity_ids"],
            session["activity_member_hash"],
            None,
            None,
            "note",
            malformed,
        )
        assert result == {"ok": False, "error": "日期无效"}, (
            f"expected '日期无效' for malformed date '{malformed}', "
            f"got '{result.get('error')}'"
        )


def test_save_timeline_session_override_too_long_note(bridge):
    """Notes exceeding the max length must be rejected with 备注过长."""
    from worktrace.api import timeline_api

    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    long_note = "x" * (timeline_api.TIMELINE_NOTE_MAX_LENGTH + 1)
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        None,
        None,
        long_note,
        "2026-06-25",
    )
    assert result == {"ok": False, "error": "备注过长"}


def test_save_timeline_session_override_non_string_note(bridge):
    """A non-string note must be rejected with 备注内容无效."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        None,
        None,
        12345,
        "2026-06-25",
    )
    assert result == {"ok": False, "error": "备注内容无效"}


# ---------------------------------------------------------------------------
# save_timeline_session_override — identity-missing
# ---------------------------------------------------------------------------


def test_save_timeline_session_override_empty_hash_rejected(bridge):
    """An empty ``activity_member_hash`` must be rejected with
    请选择有效的活动."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        "",
        None,
        None,
        "note",
        "2026-06-25",
    )
    assert result == {"ok": False, "error": "请选择有效的活动"}


def test_save_timeline_session_override_empty_date_rejected(bridge):
    """An empty ``report_date`` must be rejected with 日期无效."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        None,
        None,
        "note",
        "",
    )
    assert result == {"ok": False, "error": "日期无效"}


def test_save_timeline_session_override_malformed_date_rejected(bridge):
    """A malformed ``report_date`` must be rejected with 日期无效."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        session["activity_member_hash"],
        None,
        None,
        "note",
        "not-a-date",
    )
    assert result == {"ok": False, "error": "日期无效"}


# ---------------------------------------------------------------------------
# save_timeline_session_override — safety / security
# ---------------------------------------------------------------------------


def test_save_timeline_session_override_no_traceback_on_error(bridge):
    """Unexpected exceptions must return a generic error without leaking the
    underlying exception message or traceback text."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.save_timeline_session_override",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.save_timeline_session_override(
            session["activity_ids"],
            session["activity_member_hash"],
            None,
            None,
            "note",
            "2026-06-25",
        )
    assert result == {"ok": False, "error": "操作失败"}
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_save_timeline_session_override_error_has_no_sensitive_keys(bridge):
    """Error payloads must not expose sensitive raw fields at any level."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.save_timeline_session_override",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.save_timeline_session_override(
            session["activity_ids"],
            session["activity_member_hash"],
            None,
            None,
            "note",
            "2026-06-25",
        )
    _assert_no_sensitive_keys(result)


def test_save_timeline_session_override_validation_error_no_sensitive_details(bridge):
    """When the API raises ``ValueError`` for a nonexistent activity, the
    bridge must return a generic error without echoing the underlying
    ValueError text."""
    valid_hash = "a" * 40
    result = bridge.save_timeline_session_override(
        [999999],
        valid_hash,
        None,
        None,
        "note",
        "2026-06-25",
    )
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "activity_id" not in str(result).lower()
    assert "does not exist" not in str(result).lower()


def test_save_timeline_session_override_does_not_log_note_content(bridge, caplog):
    """The bridge must never log the note content, even on error."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    secret_note = "THIS_IS_A_SECRET_NOTE_THAT_MUST_NOT_APPEAR_IN_LOGS"
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.save_timeline_session_override",
        side_effect=RuntimeError("boom"),
    ):
        with caplog.at_level("ERROR"):
            bridge.save_timeline_session_override(
                session["activity_ids"],
                session["activity_member_hash"],
                None,
                None,
                secret_note,
                "2026-06-25",
            )
    # The note content must not appear in any log record.
    for record in caplog.records:
        assert secret_note not in record.getMessage()
        assert secret_note not in str(record.exc_info or "")


def test_save_timeline_session_override_does_not_log_sensitive_data(bridge, caplog):
    """The bridge must never log window titles, file paths, or clipboard
    content, even on error."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    sensitive_markers = ["window_title", "file_path_hint", "clipboard", "traceback"]
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.save_timeline_session_override",
        side_effect=RuntimeError("boom with window_title and file_path_hint"),
    ):
        with caplog.at_level("ERROR"):
            bridge.save_timeline_session_override(
                session["activity_ids"],
                session["activity_member_hash"],
                None,
                None,
                "note",
                "2026-06-25",
            )
    for record in caplog.records:
        msg = record.getMessage()
        for marker in sensitive_markers:
            # The exception message itself may contain these words because
            # the test injected them; what matters is that the bridge does
            # not add them. We only check the bridge's own log format line
            # ("webview bridge ... failed"), not the full traceback.
            if "webview bridge" in msg:
                assert marker not in msg.lower()


def test_save_timeline_session_override_session_identity_conflict(bridge):
    """A valid-looking but wrong ``activity_member_hash`` means the session
    can no longer be resolved (e.g. project rules re-grouped it). The bridge
    must return the contract message, not a raw error."""
    ids = _seed_session()
    session = _session_for("2026-06-25", ids[0])
    # A syntactically valid 40-char hex hash that does not match any session.
    wrong_hash = "f" * 40
    result = bridge.save_timeline_session_override(
        session["activity_ids"],
        wrong_hash,
        None,
        None,
        "note",
        "2026-06-25",
    )
    assert result == {"ok": False, "error": "该编辑因项目规则更新发生重排，请重新确认。"}


# ---------------------------------------------------------------------------
# Backend boundary (kept)
# ---------------------------------------------------------------------------


def test_bridge_module_does_not_import_backend_internals():
    """The bridge must only import worktrace.api, not services/db/collector/
    security. This is also enforced by test_ui_backend_boundary.py but is
    re-asserted here for the editing surface."""
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
