"""Tests for the WebView bridge Statistics / Export summary method.

Covers ``WebViewBridge.get_statistics_export_summary``:

- success returns ``{"ok": true, "summary": {...}}`` with display-safe fields;
- invalid date / invalid range / too-large range return stable Chinese
  messages with ``summary: null``;
- unexpected exceptions collapse to ``加载统计失败`` without echoing
  tracebacks, SQL, raw exception text, window_title, file_path_hint,
  full_path, clipboard, or note;
- the bridge does not import backend internals (services / db / collector /
  runtime / security / config);
- the bridge method is read-only: it never writes to the DB, never writes a
  file, and never opens a save dialog.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from worktrace.api import statistics_api
from worktrace.api.statistics_api import StatisticsSummaryError
from tests.support import activity_factory as activity_service
from worktrace.services import (
    project_service,
    settings_service,
)
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    return WebViewBridge()


SENSITIVE_KEYS = (
    "window_title",
    "file_path_hint",
    "full_path",
    "clipboard",
    "note",
    "traceback",
    "exception",
    "stack",
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


def _seed_closed_activity(
    app="Word",
    process="winword.exe",
    resource="A1.docx",
    start="09:00:00",
    end="09:30:00",
    day="2026-06-25",
    project_id=None,
    note="top secret note",
    file_path_hint="C:\\Users\\secret\\A1.docx",
):
    aid = activity_service.create_activity(
        app,
        process,
        resource,
        start_time=f"{day} {start}",
        project_id=project_id,
        file_path_hint=file_path_hint,
        note=note,
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} {end}")
    return aid




def test_bridge_statistics_summary_success(bridge):
    pid = project_service.create_project("Client")
    _seed_closed_activity(day="2026-06-25", project_id=pid, app="Word")
    _seed_closed_activity(
        day="2026-06-25", project_id=pid, app="Excel", process="excel.exe",
        resource="Report.xlsx", start="10:00:00", end="10:15:00",
    )
    result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    summary = result["summary"]
    assert summary is not None
    assert summary["date_from"] == "2026-06-25"
    assert summary["date_to"] == "2026-06-25"
    assert summary["total_duration_seconds"] == 2700
    assert summary["activity_count"] == 2
    assert summary["project_count"] == 1
    assert summary["app_count"] == 2
    # Pre-formatted duration strings are present (no second bridge round-trip).
    assert summary["total_duration"] == "00:45:00"
    # by_project / by_app / by_status each have pre-formatted duration.
    for group in summary["by_project"]:
        assert "duration" in group
        assert "duration_seconds" in group
        assert "percentage" in group
    for group in summary["by_app"]:
        assert "duration" in group
    for group in summary["by_status"]:
        assert "duration" in group
    # export_preview: the CSV write action is open. timesheet is no
    # longer advertised as an available format.
    preview = summary["export_preview"]
    assert preview["export_actions_enabled"] is True
    assert preview["available_formats"] == ["csv"]
    assert preview["included_duration"] == "00:45:00"
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_empty_range(bridge):
    result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    summary = result["summary"]
    assert summary["activity_count"] == 0
    assert summary["total_duration_seconds"] == 0
    assert summary["total_duration"] == "00:00:00"
    assert summary["by_project"] == []
    assert summary["by_app"] == []
    assert summary["by_status"] == []
    _assert_no_sensitive_keys(result)




def test_bridge_statistics_summary_invalid_date_shape(bridge):
    result = bridge.get_statistics_export_summary("not-a-date", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_invalid_date_to_shape(bridge):
    result = bridge.get_statistics_export_summary("2026-06-25", "2026/06/25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_non_string_input(bridge):
    result = bridge.get_statistics_export_summary(20260625, "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)
    result2 = bridge.get_statistics_export_summary("2026-06-25", None)
    assert result2["ok"] is False
    assert result2["error"] == "请选择有效日期"
    assert result2["summary"] is None
    _assert_no_sensitive_keys(result2)




def test_bridge_statistics_summary_invalid_range(bridge):
    result = bridge.get_statistics_export_summary("2026-06-26", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期范围"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_range_too_large(bridge):
    from datetime import date, timedelta

    max_days = 31
    start = date(2026, 1, 1)
    end = start + timedelta(days=max_days)
    result = bridge.get_statistics_export_summary(start.isoformat(), end.isoformat())
    assert result["ok"] is False
    assert result["error"] == "日期范围过大"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_invalid_date_from_api(bridge):
    """An ``invalid_date`` StatisticsSummaryError maps to 请选择有效日期."""
    with patch.object(
        statistics_api,
        "get_statistics_export_summary",
        side_effect=StatisticsSummaryError("invalid_date"),
    ):
        result = bridge.get_statistics_export_summary("2026-13-45", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_invalid_range_from_api(bridge):
    with patch.object(
        statistics_api,
        "get_statistics_export_summary",
        side_effect=StatisticsSummaryError("invalid_range"),
    ):
        result = bridge.get_statistics_export_summary("2026-06-26", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期范围"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_range_too_large_from_api(bridge):
    with patch.object(
        statistics_api,
        "get_statistics_export_summary",
        side_effect=StatisticsSummaryError("range_too_large"),
    ):
        result = bridge.get_statistics_export_summary("2026-01-01", "2026-03-01")
    assert result["ok"] is False
    assert result["error"] == "日期范围过大"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_operation_failed_from_api(bridge):
    with patch.object(
        statistics_api,
        "get_statistics_export_summary",
        side_effect=StatisticsSummaryError("operation_failed"),
    ):
        result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "加载统计失败"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_unknown_error_code_collapses(bridge):
    """An unknown StatisticsSummaryError code collapses to 加载统计失败."""
    with patch.object(
        statistics_api,
        "get_statistics_export_summary",
        side_effect=StatisticsSummaryError("unknown_code"),
    ):
        result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "加载统计失败"
    assert result["summary"] is None
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_unexpected_exception_collapses(bridge):
    """An unexpected non-API exception collapses to 加载统计失败 without
    echoing the traceback."""
    with patch.object(
        statistics_api,
        "get_statistics_export_summary",
        side_effect=RuntimeError("C:\\secret\\boom.sql"),
    ):
        result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "加载统计失败"
    assert result["summary"] is None
    payload_str = str(result)
    assert "boom" not in payload_str.lower()
    assert "secret" not in payload_str.lower()
    assert "traceback" not in payload_str.lower()
    assert "sql" not in payload_str.lower()
    _assert_no_sensitive_keys(result)




def test_bridge_statistics_summary_no_raw_fields(bridge):
    """A successful summary must not surface raw window_title /
    file_path_hint / full_path / clipboard / note / traceback / sql."""
    _seed_closed_activity(
        app="Word", resource="SecretReport.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", note="top secret note",
        file_path_hint="C:\\Users\\secret\\SecretReport.docx",
    )
    result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    payload_str = str(result)
    assert "window_title" not in payload_str.lower()
    assert "file_path_hint" not in payload_str.lower()
    assert "full_path" not in payload_str.lower()
    assert "clipboard" not in payload_str.lower()
    assert "traceback" not in payload_str.lower()
    assert "sql" not in payload_str.lower()
    # The secret note content must never appear.
    assert "top secret note" not in payload_str.lower()
    # The raw file path must never appear.
    assert "c:\\\\users\\\\secret" not in payload_str.lower()
    assert "secretreport.docx" not in payload_str.lower()
    _assert_no_sensitive_keys(result)


def test_bridge_statistics_summary_display_safe_keys_only(bridge):
    """The summary payload must only contain display-safe keys."""
    pid = project_service.create_project("Client")
    _seed_closed_activity(day="2026-06-25", project_id=pid)
    result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    summary = result["summary"]
    allowed_top_keys = {
        "date_from",
        "date_to",
        "total_duration_seconds",
        "total_duration",
        "project_duration_seconds",
        "project_duration",
        "activity_count",
        "session_count",
        "export_row_count",
        "snapshot_revision",
        "project_count",
        "app_count",
        "by_project",
        "by_app",
        "by_status",
        "export_preview",
    }
    assert set(summary.keys()) <= allowed_top_keys, (
        f"unexpected top-level keys: {set(summary.keys()) - allowed_top_keys}"
    )
    allowed_group_keys = {
        "key",
        "display_name",
        "duration_seconds",
        "duration",
        "activity_count",
        "percentage",
    }
    for group in summary["by_project"] + summary["by_app"] + summary["by_status"]:
        assert set(group.keys()) <= allowed_group_keys, (
            f"unexpected group keys: {set(group.keys()) - allowed_group_keys}"
        )
    allowed_preview_keys = {
        "date_from",
        "date_to",
        "included_activity_count",
        "included_duration_seconds",
        "included_duration",
        "available_formats",
        "export_actions_enabled",
        "snapshot_revision",
        "export_row_count",
        "session_count",
    }
    assert set(summary["export_preview"].keys()) <= allowed_preview_keys
    _assert_no_sensitive_keys(result)




def test_bridge_statistics_summary_does_not_write_db(bridge, temp_db):
    """The bridge method must not INSERT / UPDATE / DELETE any row."""
    from worktrace.db import get_connection

    pid = project_service.create_project("Client")
    _seed_closed_activity(day="2026-06-25", project_id=pid)
    with get_connection() as conn:
        before_activity = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"]
        before_project = conn.execute("SELECT COUNT(*) AS c FROM project").fetchone()["c"]
    bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    with get_connection() as conn:
        after_activity = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"]
        after_project = conn.execute("SELECT COUNT(*) AS c FROM project").fetchone()["c"]
    assert after_activity == before_activity
    assert after_project == before_project


def test_bridge_statistics_summary_does_not_call_export_write(bridge):
    """The bridge method must not call any export write / file save function.
    We verify by ensuring no module-level write helper is invoked."""
    # The bridge module must not even reference save / write / export action
    # helpers. We check the source for forbidden method names.
    bridge_path = Path(__file__).resolve().parents[1] / "worktrace" / "webview_ui" / "bridge.py"
    source = bridge_path.read_text(encoding="utf-8")
    # ``get_statistics_export_summary`` must be the only statistics method.
    assert "get_statistics_export_summary" in source
    # No export write / save dialog / file creation helpers.
    forbidden = [
        "save_dialog",
        "saveas_dialog",
        "save_file_dialog",
        "export_csv",
        "export_excel",
        "export_pdf",
        "export_timesheet",
        "write_file",
        "open_folder",
        "asksaveasfilename",
    ]
    for name in forbidden:
        assert name not in source, (
            f"bridge.py must not reference export write helper '{name}'"
        )




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
