"""Tests for the WebView bridge (worktrace.webview_ui.bridge).

The bridge must:
- return JSON-serializable dicts;
- never return tracebacks;
- only import worktrace.api (enforced by test_ui_backend_boundary.py).
- never surface sensitive raw fields (window_title, file_path_hint, note,
  clipboard) in Timeline output.
- expose ``is_in_progress`` as an explicit flag passed through from the
  timeline service (not inferred from the displayed ``end_time``, which
  may be projected for open activities).
- build ``resource_name`` from sanitized display fields only, never falling
  back to the raw ``window_title`` column.
"""

from __future__ import annotations
from tests.support.db_helpers import set_activity_note

import json
from unittest.mock import patch

import pytest

from worktrace import db
from worktrace.resources.types import DetectedResource
from worktrace.services import activity_service, project_service, settings_service
from worktrace.webview_ui.bridge import WebViewBridge
from worktrace.webview_ui.bridge_common import _safe_resource_display_name

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    # toggle_pause now gates on first_run_notice_accepted.
    # Most bridge tests assume the user has already accepted the notice
    # (the normal runtime state). Accept it here so the existing
    # toggle_pause / pause / resume semantics are exercised.
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.clear_settings_cache()
    return WebViewBridge()


def test_get_status_returns_dict(bridge):
    result = bridge.get_status()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "status" in result
    assert "paused" in result
    assert "display" in result


def test_get_status_is_json_serializable(bridge):
    result = bridge.get_status()
    json.dumps(result)


def test_toggle_pause_returns_dict(bridge):
    result = bridge.toggle_pause()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "status" in result


def test_toggle_pause_is_json_serializable(bridge):
    result = bridge.toggle_pause()
    json.dumps(result)


def test_get_overview_returns_dict(bridge):
    result = bridge.get_overview()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "date" in result
    assert "overview" in result
    overview = result["overview"]
    assert "total_duration" in overview
    assert "classified_duration" in overview
    assert "uncategorized_duration" in overview
    assert "project_count" in overview
    assert "current_activity" in result


def test_get_overview_is_json_serializable(bridge):
    result = bridge.get_overview()
    json.dumps(result)


def test_get_recent_activities_returns_dict_with_list(bridge):
    result = bridge.get_recent_activities()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert isinstance(result["activities"], list)


def test_get_recent_activities_is_json_serializable(bridge):
    result = bridge.get_recent_activities()
    json.dumps(result)


def test_get_timeline_returns_dict_with_sessions(bridge):
    result = bridge.get_timeline()
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "date" in result
    assert "total_duration" in result
    assert "current_activity" in result
    assert isinstance(result["sessions"], list)


def test_get_timeline_is_json_serializable(bridge):
    result = bridge.get_timeline()
    json.dumps(result)


def test_get_timeline_with_explicit_date(bridge):
    from datetime import date as dt_date, timedelta

    today = dt_date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    result = bridge.get_timeline(yesterday)
    assert result["ok"] is True
    assert result["date"] == yesterday


def test_get_timeline_session_details_returns_dict(bridge):
    result = bridge.get_timeline_session_details([], None)
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert isinstance(result["activities"], list)
    assert result["activities"] == []


def test_get_timeline_session_details_is_json_serializable(bridge):
    result = bridge.get_timeline_session_details([], None)
    json.dumps(result)


def test_get_timeline_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_timeline.view_model_api.get_timeline_view_model",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_timeline()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_get_timeline_session_details_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_timeline.view_model_api.get_session_details_view_model",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_timeline_session_details([1], None)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_get_status_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_overview.settings_api.get_collector_status",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_status()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "traceback" not in str(result).lower()
    assert "boom" not in str(result)


def test_toggle_pause_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_overview.settings_api.get_collector_status",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.toggle_pause()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)


def test_get_overview_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_overview.view_model_api.get_overview_view_model",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_overview()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)


def test_get_recent_activities_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_overview.view_model_api.get_overview_view_model",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_recent_activities()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)


def test_toggle_pause_sets_paused_when_running(bridge):
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("user_paused", "false")
    result = bridge.toggle_pause()
    assert result["ok"] is True
    assert result["paused"] is True
    assert settings_service.get_bool_setting("user_paused") is True


def test_toggle_pause_resumes_when_paused(bridge):
    settings_service.set_setting("collector_status", "paused")
    settings_service.set_setting("user_paused", "true")
    result = bridge.toggle_pause()
    assert result["ok"] is True
    # toggle_pause clears user_paused; the collector thread updates
    # collector_status to "running" once it actually starts. Without a real
    # collector thread (test env), collector_status stays "paused", which
    # matches Tkinter behavior. Assert the user_paused flag was cleared.
    assert settings_service.get_bool_setting("user_paused") is False


# Timeline read-only validation hardening


def _seed_activity_with_sensitive_metadata(
    app: str = "Word",
    process: str = "winword.exe",
    title: str = "合同.docx - Word",
    start: str = "2026-06-25 09:00:00",
    *,
    project_id: int | None = None,
    path_hint: str | None = "D:\\Secret\\合同.docx",
    note: str | None = "client confidential note",
):
    """Seed an activity with raw sensitive metadata (window_title,
    file_path_hint, note) so tests can verify the bridge never surfaces
    those fields to the WebView UI."""
    resource = DetectedResource(
        resource_kind="office_document",
        resource_subtype="word_document",
        display_name="合同.docx",
        identity_key="file:合同.docx",
        is_anchor=True,
        confidence=90,
        source="test",
        app_name=app,
        process_name=process,
        window_title=title,
        path_hint=path_hint,
    )
    aid = activity_service.create_activity(
        app,
        process,
        title,
        start_time=start,
        project_id=project_id,
        resource=resource,
    )
    activity_service.finalize_created_activity(aid)
    if note is not None:
        set_activity_note(aid, note)
    activity_service.close_activity(aid, "2026-06-25 09:30:00")
    return aid


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
    """Walk a JSON-like payload and assert no sensitive raw fields appear at
    any level. The bridge must only surface sanitized display fields."""
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


def test_safe_resource_display_name_prefers_resource_display_name():
    """The helper must prefer the sanitized ``resource_display_name`` field."""
    row = {
        "resource_display_name": "合同.docx",
        "activity_display_name": "fallback",
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "D:\\Secret\\合同.docx - Word",
    }
    assert _safe_resource_display_name(row) == "合同.docx"


def test_safe_resource_display_name_falls_back_through_safe_chain():
    """The helper must walk resource_display_name → activity_display_name
    → app_name → process_name, skipping window_title entirely."""
    assert _safe_resource_display_name(
        {"activity_display_name": "fallback", "app_name": "Word"}
    ) == "fallback"
    assert _safe_resource_display_name({"app_name": "Word"}) == "Word"
    assert _safe_resource_display_name({"process_name": "winword.exe"}) == "winword.exe"
    assert _safe_resource_display_name({}) == "未知"


def test_safe_resource_display_name_never_returns_window_title():
    """Even when only ``window_title`` is populated, the helper must NOT
    return it; it must return ``未知`` instead."""
    row = {"window_title": "D:\\Secret\\合同.docx - Word"}
    result = _safe_resource_display_name(row)
    assert result == "未知"
    assert "Secret" not in result
    assert "合同" not in result


def test_get_timeline_session_exposes_is_in_progress_flag(bridge):
    """each Timeline session must carry ``is_in_progress`` so the
    frontend can mark open sessions distinctly from closed history."""
    project_service.create_project("A")
    activity_service.create_activity(
        "Word", "winword.exe", "A.docx",
        start_time="2026-06-25 09:00:00",
    )
    # Leave the activity open (no close_activity call) so end_time is NULL.
    result = bridge.get_timeline("2026-06-25")
    assert result["ok"] is True
    assert isinstance(result["sessions"], list)
    assert len(result["sessions"]) >= 1
    s = result["sessions"][0]
    assert "is_in_progress" in s
    assert s["is_in_progress"] is True


def test_get_timeline_session_details_exposes_is_in_progress_flag(bridge):
    """each Timeline detail row must carry ``is_in_progress``."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A.docx",
        start_time="2026-06-25 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    # Leave open so end_time is NULL.
    result = bridge.get_timeline_session_details([aid], "2026-06-25")
    assert result["ok"] is True
    assert isinstance(result["activities"], list)
    assert len(result["activities"]) == 1
    a = result["activities"][0]
    assert "is_in_progress" in a
    assert a["is_in_progress"] is True


def test_get_timeline_does_not_leak_sensitive_fields(bridge):
    """``get_timeline`` must not surface window_title,
    file_path_hint, note, clipboard, traceback, or full_path anywhere in
    its output."""
    project = project_service.create_project("A")
    _seed_activity_with_sensitive_metadata(project_id=project)
    result = bridge.get_timeline("2026-06-25")
    assert result["ok"] is True
    _assert_no_sensitive_keys(result, "get_timeline")


def test_get_timeline_session_details_does_not_leak_sensitive_fields(bridge):
    """``get_timeline_session_details`` must not surface
    window_title, file_path_hint, note, clipboard, traceback, or
    full_path anywhere in its output."""
    project = project_service.create_project("A")
    aid = _seed_activity_with_sensitive_metadata(project_id=project)
    result = bridge.get_timeline_session_details([aid], "2026-06-25")
    assert result["ok"] is True
    _assert_no_sensitive_keys(result, "get_timeline_session_details")


def test_get_timeline_session_details_resource_name_skips_window_title(bridge):
    """``resource_name`` must be built from sanitized display
    fields only. Even when the underlying row has a sensitive
    ``window_title`` containing a full path, the surfaced ``resource_name``
    must not contain that path."""
    project = project_service.create_project("A")
    sensitive_title = "D:\\Secret\\Path\\合同.docx - Word"
    aid = _seed_activity_with_sensitive_metadata(
        title=sensitive_title, project_id=project
    )
    result = bridge.get_timeline_session_details([aid], "2026-06-25")
    assert result["ok"] is True
    activities = result["activities"]
    assert len(activities) == 1
    name = activities[0]["resource_name"]
    # The sanitized basename should be returned, not the raw window_title.
    assert "Secret" not in name
    assert "D:" not in name
    # The sanitized display name should still be useful (basename present).
    assert name == "合同.docx"


def test_get_timeline_session_details_with_empty_safe_fields_returns_unknown(bridge):
    """when the activity has only a window_title containing a
    full path, the bridge must return a sanitized basename (extracted by
    the resource service) or ``未知`` — never the raw window_title with
    the full path, directory, or ``- Word`` suffix."""
    project = project_service.create_project("A")
    aid = activity_service.create_activity(
        "", "", "D:\\Secret\\only_title.docx - Word",
        start_time="2026-06-25 09:00:00",
        project_id=project,
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-25 09:10:00")
    result = bridge.get_timeline_session_details([aid], "2026-06-25")
    assert result["ok"] is True
    activities = result["activities"]
    assert len(activities) == 1
    name = activities[0]["resource_name"]
    # The full path and sensitive directory must never be leaked.
    assert "Secret" not in name
    assert "D:" not in name
    assert "\\" not in name
    # The raw ``- Word`` window-title suffix must not be leaked.
    assert "Word" not in name
    # A sanitized basename (extracted by the resource service) or ``未知``
    # is acceptable. Both are safe — neither contains the full path.
    assert name in ("only_title.docx", "未知")


def test_get_timeline_session_details_error_returns_generic_message(bridge):
    """on exception, the bridge must return the generic
    ``操作失败`` error and must not leak the underlying exception type,
    message, or any traceback."""
    with patch(
        "worktrace.webview_ui.bridge_timeline.view_model_api.get_session_details_view_model",
        side_effect=ValueError("internal secret value"),
    ):
        result = bridge.get_timeline_session_details([1, 2, 3], None)
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "internal secret value" not in serialized
    assert "ValueError" not in serialized
    assert "traceback" not in serialized.lower()


def test_get_timeline_session_details_returns_json_serializable_with_sensitive_data(bridge):
    """the bridge output must remain JSON-serializable even when
    the underlying activity rows contain sensitive raw fields."""
    project = project_service.create_project("A")
    aid = _seed_activity_with_sensitive_metadata(project_id=project)
    result = bridge.get_timeline_session_details([aid], "2026-06-25")
    # Must not raise.
    json.dumps(result)


def test_bridge_module_does_not_import_unsafe_display_helper():
    """``bridge.py`` must not import
    ``format_activity_display_name`` from ``worktrace.formatters`` because
    that helper falls back to the raw ``window_title`` column. The bridge
    uses ``_safe_resource_display_name`` instead."""
    import worktrace.webview_ui.bridge as bridge_mod

    source = open(bridge_mod.__file__, encoding="utf-8").read()
    assert "format_activity_display_name" not in source, (
        "bridge.py must not import format_activity_display_name; it falls "
        "back to the raw window_title column. Use _safe_resource_display_name."
    )




# P0: toggle_pause + unified privacy-gated startup


def test_toggle_pause_starts_collection_after_privacy_gate_when_resuming(
    bridge, monkeypatch
):
    """When the user is paused, toggling to resume must call the unified
    ``app_api.start_collection_after_privacy_gate()`` entry so the
    first-run privacy gate is enforced in exactly one place. The bridge
    must NOT call ``start_background_workers`` / ``start_collector``
    directly."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.get_collector_status",
        lambda: "paused",
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.is_user_paused", lambda: True
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.set_user_paused", lambda x: None
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.set_collector_status",
        lambda x: None,
    )

    gate_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_collection_after_privacy_gate",
        lambda: gate_calls.append(True) or {"ok": True},
    )

    # Direct start_background_workers / start_collector must NOT be called.
    direct_bg_calls: list[bool] = []
    direct_collector_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_background_workers",
        lambda: direct_bg_calls.append(True),
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_collector",
        lambda: direct_collector_calls.append(True),
    )

    result = bridge.toggle_pause()

    assert result["ok"] is True
    assert gate_calls == [True]
    assert direct_bg_calls == []
    assert direct_collector_calls == []


def test_toggle_pause_does_not_start_collection_when_gate_closed(
    bridge, monkeypatch
):
    """When the unified privacy-gate entry returns ``ok=False`` (notice
    not accepted or read failed), ``toggle_pause`` must forward the
    failure payload and must NOT mutate caller state."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.get_collector_status",
        lambda: "paused",
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.is_user_paused", lambda: True
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_collection_after_privacy_gate",
        lambda: {"ok": False, "error": "请先确认隐私说明"},
    )

    # Caller state mutators must NOT be touched when the gate fails.
    user_paused_calls: list[bool] = []
    status_calls: list[str] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.set_user_paused",
        lambda x: user_paused_calls.append(x),
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.set_collector_status",
        lambda x: status_calls.append(x),
    )

    result = bridge.toggle_pause()

    assert result["ok"] is False
    assert result["error"] == "请先确认隐私说明"
    assert user_paused_calls == []
    assert status_calls == []


def test_toggle_pause_calls_app_api_pause_entry_when_running(bridge, monkeypatch):
    """Pausing must go through ``app_api.pause_collection_now`` so the
    collector/recorder own finalization and snapshot cleanup."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.get_collector_status",
        lambda: "running",
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.is_user_paused", lambda: False
    )
    pause_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.pause_collection_now",
        lambda: pause_calls.append(True) or {"ok": True, "pause_pending": False},
    )
    clear_calls: list[str] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.clear_runtime_activity_state",
        lambda reason: clear_calls.append(reason),
        raising=False,
    )

    result = bridge.toggle_pause()

    assert result["ok"] is True
    assert pause_calls == [True]
    assert clear_calls == []


# P0: accept_first_run_notice + unified privacy-gated startup


def test_accept_first_run_notice_calls_unified_gate_on_success(
    bridge, monkeypatch
):
    """When the API returns ``ok=True``, the bridge must call the unified
    ``app_api.start_collection_after_privacy_gate()`` entry so recording
    begins immediately after the user accepts the privacy notice. The
    bridge must NOT call ``start_background_workers`` /
    ``start_collector`` directly."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.settings_api.accept_first_run_notice_for_webview",
        lambda: {"ok": True, "accepted": True},
    )

    gate_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_collection_after_privacy_gate",
        lambda: gate_calls.append(True) or {"ok": True},
    )

    # Direct start_background_workers / start_collector must NOT be called.
    direct_bg_calls: list[bool] = []
    direct_collector_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_background_workers",
        lambda: direct_bg_calls.append(True),
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_collector",
        lambda: direct_collector_calls.append(True),
    )

    result = bridge.accept_first_run_notice()

    assert result["ok"] is True
    assert gate_calls == [True]
    assert direct_bg_calls == []
    assert direct_collector_calls == []


def test_accept_first_run_notice_does_not_call_gate_on_api_failure(
    bridge, monkeypatch
):
    """When the API returns ``ok=False``, the bridge must NOT call the
    unified gate entry; it forwards the API's error payload unchanged."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.settings_api.accept_first_run_notice_for_webview",
        lambda: {"ok": False, "error": "写入失败"},
    )

    gate_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_collection_after_privacy_gate",
        lambda: gate_calls.append(True) or {"ok": True},
    )

    result = bridge.accept_first_run_notice()

    assert result["ok"] is False
    assert gate_calls == []


def test_accept_first_run_notice_succeeds_even_if_gate_raises(
    bridge, monkeypatch
):
    """The accept itself is the persisted success; a unified gate
    exception must NOT mask it. The result must still be
    ``{"ok": True, "accepted": True}``."""

    def raise_gate() -> dict:
        raise RuntimeError("gate start failed")

    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.settings_api.accept_first_run_notice_for_webview",
        lambda: {"ok": True, "accepted": True},
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_collection_after_privacy_gate",
        raise_gate,
    )

    result = bridge.accept_first_run_notice()

    assert result["ok"] is True
    assert result["accepted"] is True


# P2: get_overview / get_timeline ticker payload


def test_get_overview_returns_snapshot_and_seconds_fields(bridge):
    """``get_overview`` must return ``today_total_seconds`` and
    ``current_activity_elapsed_seconds`` as ints, and the
    ``current_activity`` dict must include ``elapsed_seconds`` (int) and
    ``is_paused`` (bool) so the frontend 1-second ticker can increment
    the display without a bridge round-trip."""
    settings_service.clear_settings_cache()
    result = bridge.get_overview()

    assert result["ok"] is True
    assert isinstance(result["today_total_seconds"], int)
    assert isinstance(result["current_activity_elapsed_seconds"], int)
    current = result["current_activity"]
    assert isinstance(current, dict)
    assert isinstance(current["elapsed_seconds"], int)
    assert isinstance(current["is_paused"], bool)


def test_get_timeline_returns_total_seconds_and_snapshot_fields(bridge):
    """``get_timeline`` must return ``total_seconds``,
    ``today_total_seconds``, and ``current_activity_elapsed_seconds`` as
    ints, and each session in ``sessions`` must include
    ``duration_seconds`` (int) so the frontend 1-second ticker can
    increment the displayed total and in-progress session duration
    without a bridge round-trip."""
    settings_service.clear_settings_cache()
    result = bridge.get_timeline()

    assert result["ok"] is True
    assert isinstance(result["total_seconds"], int)
    assert isinstance(result["today_total_seconds"], int)
    assert isinstance(result["current_activity_elapsed_seconds"], int)
    assert isinstance(result["sessions"], list)
    for session in result["sessions"]:
        assert isinstance(session["duration_seconds"], int)




def test_get_overview_returns_classified_and_uncategorized_seconds(bridge):
    """``get_overview`` must include ``classified_seconds`` and
    ``uncategorized_seconds`` as ints so the frontend ticker can update
    kpi-classified / kpi-uncategorized without parsing duration strings."""
    settings_service.clear_settings_cache()
    result = bridge.get_overview()

    assert result["ok"] is True
    assert "classified_seconds" in result
    assert "uncategorized_seconds" in result
    assert isinstance(result["classified_seconds"], int)
    assert isinstance(result["uncategorized_seconds"], int)


def test_get_overview_current_activity_has_classification_flags(bridge):
    """``current_activity`` must include ``is_classified`` and
    ``is_uncategorized`` booleans so the frontend ticker knows which KPI
    to increment (only one of the two, never both)."""
    settings_service.clear_settings_cache()
    result = bridge.get_overview()

    assert result["ok"] is True
    current = result["current_activity"]
    assert isinstance(current, dict)
    assert "is_classified" in current
    assert "is_uncategorized" in current
    assert isinstance(current["is_classified"], bool)
    assert isinstance(current["is_uncategorized"], bool)


def test_get_overview_classified_plus_uncategorized_le_total(bridge):
    """``classified_seconds + uncategorized_seconds`` must be <=
    ``today_total_seconds`` (the KPIs must not double-count)."""
    settings_service.clear_settings_cache()
    result = bridge.get_overview()

    assert result["ok"] is True
    total = result["today_total_seconds"]
    classified = result["classified_seconds"]
    uncategorized = result["uncategorized_seconds"]
    assert classified + uncategorized <= total


def test_get_overview_classified_uncategorized_match_string_durations(bridge):
    """The numeric ``classified_seconds`` / ``uncategorized_seconds``
    must be consistent with the ``classified_duration`` /
    ``uncategorized_duration`` string fields inside ``overview`` (both
    derive from the same underlying summary)."""
    settings_service.clear_settings_cache()
    result = bridge.get_overview()

    assert result["ok"] is True
    overview = result["overview"]
    # Parse the HH:MM:SS strings and verify they match the int seconds.
    def _parse_hms(s: str) -> int:
        parts = s.split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

    assert result["classified_seconds"] == _parse_hms(overview["classified_duration"])
    assert result["uncategorized_seconds"] == _parse_hms(
        overview["uncategorized_duration"]
    )
