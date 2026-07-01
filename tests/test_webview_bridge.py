"""Tests for the WebView bridge (worktrace.webview_ui.bridge).

The bridge must:
- return JSON-serializable dicts;
- never return tracebacks;
- only import worktrace.api (enforced by test_ui_backend_boundary.py).
- never surface sensitive raw fields (window_title, file_path_hint, note,
  clipboard) in Timeline output (Phase 2.1).
- expose ``is_in_progress`` as an explicit flag passed through from the
  timeline service (not inferred from the displayed ``end_time``, which
  may be projected for open activities) (Phase 2.1).
- build ``resource_name`` from sanitized display fields only, never falling
  back to the raw ``window_title`` column (Phase 2.1).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from worktrace import db
from worktrace.resources.types import DetectedResource
from worktrace.services import activity_service, project_service, settings_service
from worktrace.webview_ui.bridge import WebViewBridge
from worktrace.webview_ui.bridge_common import _safe_resource_display_name


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    # Phase 6E: toggle_pause now gates on first_run_notice_accepted.
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
    assert "total_duration" in result
    assert "classified_duration" in result
    assert "uncategorized_duration" in result
    assert "project_count" in result
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
        "worktrace.webview_ui.bridge_timeline.timeline_api.get_default_report_date",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_timeline()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)
    assert "traceback" not in str(result).lower()


def test_get_timeline_session_details_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.get_default_report_date",
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
        "worktrace.webview_ui.bridge_overview.timeline_api.get_default_report_date",
        side_effect=RuntimeError("boom"),
    ):
        result = bridge.get_overview()
    assert result["ok"] is False
    assert result["error"] == "操作失败"
    assert "boom" not in str(result)


def test_get_recent_activities_no_traceback_on_error(bridge):
    with patch(
        "worktrace.webview_ui.bridge_overview.timeline_api.get_default_report_date",
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


# ---------------------------------------------------------------------------
# Phase 2.1: Timeline read-only validation hardening
# ---------------------------------------------------------------------------


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
        activity_service.update_activity_note(aid, note)
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
    """Phase 2.1: each Timeline session must carry ``is_in_progress`` so the
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
    """Phase 2.1: each Timeline detail row must carry ``is_in_progress``."""
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
    """Phase 2.1: ``get_timeline`` must not surface window_title,
    file_path_hint, note, clipboard, traceback, or full_path anywhere in
    its output."""
    project = project_service.create_project("A")
    _seed_activity_with_sensitive_metadata(project_id=project)
    result = bridge.get_timeline("2026-06-25")
    assert result["ok"] is True
    _assert_no_sensitive_keys(result, "get_timeline")


def test_get_timeline_session_details_does_not_leak_sensitive_fields(bridge):
    """Phase 2.1: ``get_timeline_session_details`` must not surface
    window_title, file_path_hint, note, clipboard, traceback, or
    full_path anywhere in its output."""
    project = project_service.create_project("A")
    aid = _seed_activity_with_sensitive_metadata(project_id=project)
    result = bridge.get_timeline_session_details([aid], "2026-06-25")
    assert result["ok"] is True
    _assert_no_sensitive_keys(result, "get_timeline_session_details")


def test_get_timeline_session_details_resource_name_skips_window_title(bridge):
    """Phase 2.1: ``resource_name`` must be built from sanitized display
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
    """Phase 2.1: when the activity has only a window_title containing a
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
    """Phase 2.1: on exception, the bridge must return the generic
    ``操作失败`` error and must not leak the underlying exception type,
    message, or any traceback."""
    with patch(
        "worktrace.webview_ui.bridge_timeline.timeline_api.get_default_report_date",
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
    """Phase 2.1: the bridge output must remain JSON-serializable even when
    the underlying activity rows contain sensitive raw fields."""
    project = project_service.create_project("A")
    aid = _seed_activity_with_sensitive_metadata(project_id=project)
    result = bridge.get_timeline_session_details([aid], "2026-06-25")
    # Must not raise.
    json.dumps(result)


def test_bridge_module_does_not_import_unsafe_display_helper():
    """Phase 2.1: ``bridge.py`` must not import
    ``format_activity_display_name`` from ``worktrace.formatters`` because
    that helper falls back to the raw ``window_title`` column. The bridge
    uses ``_safe_resource_display_name`` instead."""
    import worktrace.webview_ui.bridge as bridge_mod

    source = open(bridge_mod.__file__, encoding="utf-8").read()
    assert "format_activity_display_name" not in source, (
        "bridge.py must not import format_activity_display_name; it falls "
        "back to the raw window_title column. Use _safe_resource_display_name."
    )


# --- Phase 6G: P0 privacy gate + P2 ticker payload tests ---


# P0: toggle_pause + start_background_workers


def test_toggle_pause_starts_background_workers_and_collector_when_resuming(
    bridge, monkeypatch
):
    """When the notice is accepted and the user is paused, toggling to
    resume must call BOTH ``start_background_workers`` AND
    ``start_collector`` so the folder index is warm before the collector
    starts matching activities."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.first_run_notice_accepted",
        lambda: True,
    )
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
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.set_current_activity_snapshot",
        lambda x: None,
    )

    calls: list[str] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_background_workers",
        lambda: calls.append("background_workers"),
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_collector",
        lambda: calls.append("collector"),
    )

    result = bridge.toggle_pause()

    assert result["ok"] is True
    assert "background_workers" in calls
    assert "collector" in calls


def test_toggle_pause_starts_background_workers_before_collector(bridge, monkeypatch):
    """On the resume path, ``start_background_workers`` must be called
    BEFORE ``start_collector`` so the folder index worker is running by
    the time the collector starts matching activities."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.first_run_notice_accepted",
        lambda: True,
    )
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
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.set_current_activity_snapshot",
        lambda x: None,
    )

    order: list[str] = []

    def fake_start_background_workers() -> None:
        order.append("background_workers")

    def fake_start_collector() -> None:
        order.append("collector")

    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_background_workers",
        fake_start_background_workers,
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_collector",
        fake_start_collector,
    )

    bridge.toggle_pause()

    assert order == ["background_workers", "collector"]


def test_toggle_pause_does_not_start_background_workers_when_gate_closed(
    bridge, monkeypatch
):
    """When the first-run notice has NOT been accepted, ``toggle_pause``
    must fail closed and must NOT call ``start_background_workers`` or
    ``start_collector``."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.first_run_notice_accepted",
        lambda: False,
    )

    bg_calls: list[bool] = []
    collector_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_background_workers",
        lambda: bg_calls.append(True),
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_collector",
        lambda: collector_calls.append(True),
    )

    result = bridge.toggle_pause()

    assert result["ok"] is False
    assert result["error"] == "请先确认隐私说明"
    assert bg_calls == []
    assert collector_calls == []


def test_toggle_pause_does_not_start_background_workers_when_gate_read_raises(
    bridge, monkeypatch
):
    """When ``first_run_notice_accepted`` raises, ``toggle_pause`` must
    fail closed and must NOT call ``start_background_workers`` or
    ``start_collector`` (fail-closed on settings read error)."""

    def raise_on_read() -> bool:
        raise RuntimeError("settings read failed")

    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.settings_api.first_run_notice_accepted",
        raise_on_read,
    )

    bg_calls: list[bool] = []
    collector_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_background_workers",
        lambda: bg_calls.append(True),
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.app_api.start_collector",
        lambda: collector_calls.append(True),
    )

    result = bridge.toggle_pause()

    assert result["ok"] is False
    assert result["error"] == "请先确认隐私说明"
    assert bg_calls == []
    assert collector_calls == []


# P0: accept_first_run_notice + start_background_workers


def test_accept_first_run_notice_starts_background_workers_and_collector_on_success(
    bridge, monkeypatch
):
    """When the API returns ``ok=True``, the bridge must call BOTH
    ``start_background_workers`` AND ``start_collector`` so recording
    begins immediately after the user accepts the privacy notice."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.settings_api.accept_first_run_notice_for_webview",
        lambda: {"ok": True, "accepted": True},
    )

    bg_calls: list[bool] = []
    collector_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_background_workers",
        lambda: bg_calls.append(True),
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_collector",
        lambda: collector_calls.append(True),
    )

    result = bridge.accept_first_run_notice()

    assert result["ok"] is True
    assert bg_calls == [True]
    assert collector_calls == [True]


def test_accept_first_run_notice_starts_background_workers_before_collector(
    bridge, monkeypatch
):
    """On a successful accept, ``start_background_workers`` must be called
    BEFORE ``start_collector`` so the folder index is warm before the
    collector starts matching activities."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.settings_api.accept_first_run_notice_for_webview",
        lambda: {"ok": True, "accepted": True},
    )

    order: list[str] = []

    def fake_start_background_workers() -> None:
        order.append("background_workers")

    def fake_start_collector() -> None:
        order.append("collector")

    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_background_workers",
        fake_start_background_workers,
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_collector",
        fake_start_collector,
    )

    bridge.accept_first_run_notice()

    assert order == ["background_workers", "collector"]


def test_accept_first_run_notice_does_not_start_background_workers_on_api_failure(
    bridge, monkeypatch
):
    """When the API returns ``ok=False``, the bridge must NOT call
    ``start_background_workers`` or ``start_collector``; it forwards the
    API's error payload unchanged."""
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.settings_api.accept_first_run_notice_for_webview",
        lambda: {"ok": False, "error": "写入失败"},
    )

    bg_calls: list[bool] = []
    collector_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_background_workers",
        lambda: bg_calls.append(True),
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_collector",
        lambda: collector_calls.append(True),
    )

    result = bridge.accept_first_run_notice()

    assert result["ok"] is False
    assert bg_calls == []
    assert collector_calls == []


def test_accept_first_run_notice_succeeds_even_if_background_workers_start_fails(
    bridge, monkeypatch
):
    """The accept itself is the persisted success; a background workers
    start failure must NOT mask it. The result must still be
    ``{"ok": True, ...}`` and ``start_collector`` must still be called."""

    def raise_bg() -> None:
        raise RuntimeError("worker start failed")

    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.settings_api.accept_first_run_notice_for_webview",
        lambda: {"ok": True, "accepted": True},
    )
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_background_workers", raise_bg
    )
    collector_calls: list[bool] = []
    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_settings.app_api.start_collector",
        lambda: collector_calls.append(True),
    )

    result = bridge.accept_first_run_notice()

    assert result["ok"] is True
    assert result["accepted"] is True
    assert collector_calls == [True]


# P2: get_overview / get_timeline ticker payload


def test_get_overview_returns_snapshot_and_seconds_fields(bridge):
    """Phase 6G: ``get_overview`` must return ``today_total_seconds`` and
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
    """Phase 6G: ``get_timeline`` must return ``total_seconds``,
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


# --- Overview ticker: classified / uncategorized raw seconds -----------
# The 1-second local ticker must update kpi-total / kpi-classified /
# kpi-uncategorized on the same口径 (same basis). The backend
# ``get_overview`` payload must include numeric ``classified_seconds``
# and ``uncategorized_seconds`` fields (raw ints, not parsed from
# ``HH:MM:SS`` strings) plus ``current_activity.is_classified`` /
# ``current_activity.is_uncategorized`` so the frontend knows which
# KPI to increment.


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
    must be consistent with the legacy ``classified_duration`` /
    ``uncategorized_duration`` string fields (both derive from the same
    underlying summary)."""
    settings_service.clear_settings_cache()
    result = bridge.get_overview()

    assert result["ok"] is True
    # Parse the HH:MM:SS strings and verify they match the int seconds.
    def _parse_hms(s: str) -> int:
        parts = s.split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

    assert result["classified_seconds"] == _parse_hms(result["classified_duration"])
    assert result["uncategorized_seconds"] == _parse_hms(
        result["uncategorized_duration"]
    )
