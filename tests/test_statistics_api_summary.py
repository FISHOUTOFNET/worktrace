"""Tests for the read-only Statistics / Export summary.

Covers ``worktrace.api.statistics_api.get_statistics_export_summary`` and
``worktrace.services.statistics_service.get_statistics_export_summary``:

- valid date range returns a display-safe summary with correct aggregation;
- invalid date / invalid range / too-large range raise
  ``StatisticsSummaryError`` with stable codes;
- empty range returns zero summary;
- hidden / deleted activities are excluded;
- in-progress activities are excluded (no live projection);
- by_project / by_app / by_status group correctly;
- total_duration_seconds / activity_count are correct;
- no raw DB rows / window_title / file_path_hint / full_path / clipboard /
  note are returned;
- no DB write occurs (schema unchanged, no INSERT/UPDATE/DELETE);
- export_preview reports ``export_actions_enabled = False`` and the
  documented ``available_formats`` list.
"""

from __future__ import annotations

from datetime import date

import pytest

from worktrace.api import statistics_api
from worktrace.api.statistics_api import StatisticsSummaryError
from worktrace.db import get_connection
from worktrace.formatters import format_status_label
from worktrace.services import activity_service, project_service, statistics_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


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
    status="normal",
    note="secret note",
    file_path_hint="C:\\Users\\secret\\A1.docx",
):
    aid = activity_service.create_activity(
        app,
        process,
        resource,
        status=status,
        start_time=f"{day} {start}",
        project_id=project_id,
        file_path_hint=file_path_hint,
        note=note,
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, f"{day} {end}")
    return aid




def test_service_summary_valid_range_returns_aggregated_data(temp_db):
    pid = project_service.create_project("Client")
    _seed_closed_activity(
        app="Word",
        process="winword.exe",
        resource="A1.docx",
        start="09:00:00",
        end="09:30:00",
        day="2026-06-25",
        project_id=pid,
    )
    _seed_closed_activity(
        app="Excel",
        process="excel.exe",
        resource="Report.xlsx",
        start="10:00:00",
        end="10:15:00",
        day="2026-06-25",
        project_id=pid,
    )
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert summary["date_from"] == "2026-06-25"
    assert summary["date_to"] == "2026-06-25"
    assert summary["total_duration_seconds"] == 2700  # 1800 + 900
    assert summary["activity_count"] == 2
    assert summary["project_count"] == 1
    assert summary["app_count"] == 2
    _assert_no_sensitive_keys(summary)


def test_service_summary_by_project_groups_correctly(temp_db):
    pid_a = project_service.create_project("A")
    pid_b = project_service.create_project("B")
    _seed_closed_activity(
        app="Word", resource="A1.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", project_id=pid_a,
    )
    _seed_closed_activity(
        app="Word", resource="A2.docx", start="10:00:00", end="10:15:00",
        day="2026-06-25", project_id=pid_a,
    )
    _seed_closed_activity(
        app="Excel", resource="B1.xlsx", start="11:00:00", end="11:10:00",
        day="2026-06-25", project_id=pid_b,
    )
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    by_project = {g["display_name"]: g for g in summary["by_project"]}
    assert "A" in by_project
    assert "B" in by_project
    assert by_project["A"]["duration_seconds"] == 2700  # 1800 + 900
    assert by_project["A"]["activity_count"] == 2
    assert by_project["B"]["duration_seconds"] == 600
    assert by_project["B"]["activity_count"] == 1
    # Percentage is rounded to 1 decimal.
    assert by_project["A"]["percentage"] == pytest.approx(81.8, abs=0.1)
    assert by_project["B"]["percentage"] == pytest.approx(18.2, abs=0.1)
    _assert_no_sensitive_keys(summary)


def test_service_summary_by_app_groups_correctly(temp_db):
    pid = project_service.create_project("Client")
    _seed_closed_activity(
        app="Word", resource="A1.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", project_id=pid,
    )
    _seed_closed_activity(
        app="Excel", resource="B1.xlsx", start="10:00:00", end="10:15:00",
        day="2026-06-25", project_id=pid,
    )
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    by_app = {g["display_name"]: g for g in summary["by_app"]}
    assert "Word" in by_app
    assert "Excel" in by_app
    assert by_app["Word"]["duration_seconds"] == 1800
    assert by_app["Excel"]["duration_seconds"] == 900
    _assert_no_sensitive_keys(summary)


def test_service_summary_by_status_groups_correctly(temp_db):
    pid = project_service.create_project("Client")
    _seed_closed_activity(
        app="Word", resource="A1.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", project_id=pid, status="normal",
    )
    _seed_closed_activity(
        app="空闲", process="idle", resource="用户空闲", start="10:00:00", end="10:15:00",
        day="2026-06-25", project_id=pid, status="idle",
    )
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    by_status = {g["key"]: g for g in summary["by_status"]}
    assert "normal" in by_status
    assert "idle" in by_status
    assert by_status["normal"]["display_name"] == "正常"
    assert by_status["idle"]["display_name"] == "空闲"
    assert by_status["normal"]["duration_seconds"] == 1800
    assert by_status["idle"]["duration_seconds"] == 900
    _assert_no_sensitive_keys(summary)


def test_service_summary_unknown_status_falls_back(temp_db):
    assert format_status_label("weird") == "未知状态"
    assert format_status_label(None) == "未知状态"


def test_service_summary_project_stats_only_include_normal_status_rows(temp_db):
    pid = project_service.create_project("A")
    _seed_closed_activity(
        app="Word", resource="A.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", project_id=pid, status="normal",
    )
    _seed_closed_activity(
        app="空闲", process="idle", resource="用户空闲", start="10:00:00", end="10:10:00",
        day="2026-06-25", project_id=pid, status="idle",
    )
    _seed_closed_activity(
        app="已暂停", process="paused", resource="采集已暂停", start="10:10:00", end="10:15:00",
        day="2026-06-25", project_id=pid, status="paused",
    )
    _seed_closed_activity(
        app="异常", process="error", resource="采集异常", start="10:15:00", end="10:20:00",
        day="2026-06-25", project_id=pid, status="error",
    )

    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert summary["total_duration_seconds"] == 3000
    assert summary["project_duration_seconds"] == 1800
    assert summary["activity_count"] == 4
    assert summary["project_count"] == 1

    by_project = {g["display_name"]: g for g in summary["by_project"]}
    assert list(by_project) == ["A"]
    assert by_project["A"]["duration_seconds"] == 1800
    assert by_project["A"]["percentage"] == pytest.approx(100.0)

    by_status = {g["key"]: g for g in summary["by_status"]}
    assert set(by_status) == {"normal", "idle", "paused", "error"}
    assert by_status["normal"]["duration_seconds"] == 1800
    assert by_status["idle"]["duration_seconds"] == 600
    assert by_status["paused"]["duration_seconds"] == 300
    assert by_status["error"]["duration_seconds"] == 300
    assert by_status["normal"]["percentage"] == pytest.approx(60.0)


def test_service_summary_empty_range_returns_zero(temp_db):
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert summary["total_duration_seconds"] == 0
    assert summary["activity_count"] == 0
    assert summary["project_count"] == 0
    assert summary["app_count"] == 0
    assert summary["by_project"] == []
    assert summary["by_app"] == []
    assert summary["by_status"] == []
    _assert_no_sensitive_keys(summary)


def test_service_summary_excludes_hidden_activities(temp_db):
    pid = project_service.create_project("Client")
    aid = _seed_closed_activity(
        app="Word", resource="A1.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", project_id=pid,
    )
    with get_connection() as conn:
        conn.execute("UPDATE activity_log SET is_hidden = 1 WHERE id = ?", (aid,))
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert summary["activity_count"] == 0
    assert summary["total_duration_seconds"] == 0
    _assert_no_sensitive_keys(summary)


def test_service_summary_excludes_deleted_activities(temp_db):
    pid = project_service.create_project("Client")
    aid = _seed_closed_activity(
        app="Word", resource="A1.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", project_id=pid,
    )
    with get_connection() as conn:
        conn.execute("UPDATE activity_log SET is_deleted = 1 WHERE id = ?", (aid,))
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert summary["activity_count"] == 0
    assert summary["total_duration_seconds"] == 0
    _assert_no_sensitive_keys(summary)


def test_service_summary_excludes_in_progress_activities(temp_db):
    """intentionally does NOT project live time. An open activity
    (end_time IS NULL) must be excluded from the summary."""
    pid = project_service.create_project("Client")
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx", start_time="2026-06-25 09:00:00",
        project_id=pid,
    )
    activity_service.finalize_created_activity(aid)
    # Do NOT close it; it stays in-progress.
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert summary["activity_count"] == 0
    assert summary["total_duration_seconds"] == 0
    _assert_no_sensitive_keys(summary)


def test_service_summary_export_preview_read_only(temp_db):
    _seed_closed_activity(day="2026-06-25")
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    preview = summary["export_preview"]
    assert preview["date_from"] == "2026-06-25"
    assert preview["date_to"] == "2026-06-25"
    assert preview["included_activity_count"] == 1
    assert preview["included_duration_seconds"] == 1800
    # only CSV export is enabled; timesheet is not yet supported.
    # The export action button is now enabled (CSV write is open).
    assert preview["available_formats"] == ["csv"]
    assert preview["export_actions_enabled"] is True
    _assert_no_sensitive_keys(preview)


def test_service_summary_no_raw_db_rows(temp_db):
    """The summary must not contain raw DB column names or row dicts."""
    _seed_closed_activity(
        app="Word", resource="Secret.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", note="top secret", file_path_hint="C:\\secret\\Secret.docx",
    )
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    payload_str = str(summary)
    assert "window_title" not in payload_str.lower()
    assert "file_path_hint" not in payload_str.lower()
    assert "full_path" not in payload_str.lower()
    assert "clipboard" not in payload_str.lower()
    # Note content must never be surfaced. The display-safe payload may
    # contain the key "note" only in error, so check the actual secret text.
    assert "top secret" not in payload_str.lower()
    # file_path_hint value must never be surfaced.
    assert "c:\\\\secret" not in payload_str.lower()
    assert "secret.docx" not in payload_str.lower()


def test_service_summary_multi_day_range(temp_db):
    pid = project_service.create_project("Client")
    _seed_closed_activity(
        app="Word", resource="A1.docx", start="09:00:00", end="09:30:00",
        day="2026-06-25", project_id=pid,
    )
    _seed_closed_activity(
        app="Excel", resource="B1.xlsx", start="10:00:00", end="10:15:00",
        day="2026-06-26", project_id=pid,
    )
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-26")
    assert summary["activity_count"] == 2
    assert summary["total_duration_seconds"] == 2700
    _assert_no_sensitive_keys(summary)




def test_service_summary_invalid_date_raises(temp_db):
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary("not-a-date", "2026-06-25")
    assert "invalid_date" in str(exc.value)


def test_service_summary_invalid_date_to_raises(temp_db):
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary("2026-06-25", "2026/06/25")
    assert "invalid_date" in str(exc.value)


def test_service_summary_invalid_range_raises(temp_db):
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary("2026-06-26", "2026-06-25")
    assert "invalid_range" in str(exc.value)


def test_service_summary_range_too_large_raises(temp_db):
    """A span wider than STATISTICS_SUMMARY_MAX_RANGE_DAYS is rejected."""
    max_days = statistics_service.STATISTICS_SUMMARY_MAX_RANGE_DAYS
    start = date(2026, 1, 1)
    end = start.replace(day=1)
    # Build an end date that is exactly max_days days after start, which is
    # allowed (inclusive span = max_days). Then add one more day to exceed.
    from datetime import timedelta

    end_too_large = start + timedelta(days=max_days)
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary(
            start.isoformat(), end_too_large.isoformat()
        )
    assert "range_too_large" in str(exc.value)


def test_service_summary_max_allowed_range_succeeds(temp_db):
    """An inclusive span of exactly STATISTICS_SUMMARY_MAX_RANGE_DAYS is
    allowed (e.g. 2026-06-01..2026-07-01 for a 31-day limit)."""
    max_days = statistics_service.STATISTICS_SUMMARY_MAX_RANGE_DAYS
    from datetime import timedelta

    start = date(2026, 6, 1)
    end = start + timedelta(days=max_days - 1)
    summary = statistics_service.get_statistics_export_summary(
        start.isoformat(), end.isoformat()
    )
    assert summary["date_from"] == start.isoformat()
    assert summary["date_to"] == end.isoformat()
    _assert_no_sensitive_keys(summary)




def test_service_summary_does_not_write_db(temp_db):
    """The summary must not INSERT / UPDATE / DELETE any row. We verify by
    recording the row counts before and after the call."""
    pid = project_service.create_project("Client")
    _seed_closed_activity(day="2026-06-25", project_id=pid)
    with get_connection() as conn:
        before_activity = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"]
        before_project = conn.execute("SELECT COUNT(*) AS c FROM project").fetchone()["c"]
        before_resource = conn.execute("SELECT COUNT(*) AS c FROM activity_resource").fetchone()["c"]
    statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    with get_connection() as conn:
        after_activity = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"]
        after_project = conn.execute("SELECT COUNT(*) AS c FROM project").fetchone()["c"]
        after_resource = conn.execute("SELECT COUNT(*) AS c FROM activity_resource").fetchone()["c"]
    assert after_activity == before_activity
    assert after_project == before_project
    assert after_resource == before_resource


def test_service_summary_does_not_update_updated_at(temp_db):
    """The summary must not bump ``updated_at`` on any activity row."""
    pid = project_service.create_project("Client")
    aid = _seed_closed_activity(day="2026-06-25", project_id=pid)
    with get_connection() as conn:
        before = conn.execute(
            "SELECT updated_at FROM activity_log WHERE id = ?", (aid,)
        ).fetchone()["updated_at"]
    statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    with get_connection() as conn:
        after = conn.execute(
            "SELECT updated_at FROM activity_log WHERE id = ?", (aid,)
        ).fetchone()["updated_at"]
    assert after == before




def test_api_summary_valid_range_returns_summary(temp_db):
    pid = project_service.create_project("Client")
    _seed_closed_activity(day="2026-06-25", project_id=pid)
    summary = statistics_api.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert summary["activity_count"] == 1
    assert summary["total_duration_seconds"] == 1800
    _assert_no_sensitive_keys(summary)


def test_api_summary_invalid_date_raises_error(temp_db):
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary("not-a-date", "2026-06-25")
    assert exc.value.code == "invalid_date"


def test_api_summary_invalid_range_raises_error(temp_db):
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary("2026-06-26", "2026-06-25")
    assert exc.value.code == "invalid_range"


def test_api_summary_range_too_large_raises_error(temp_db):
    max_days = statistics_service.STATISTICS_SUMMARY_MAX_RANGE_DAYS
    from datetime import timedelta

    start = date(2026, 1, 1)
    end = start + timedelta(days=max_days)
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary(start.isoformat(), end.isoformat())
    assert exc.value.code == "range_too_large"


def test_api_summary_non_string_input_raises_error(temp_db):
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary(20260625, "2026-06-25")
    assert exc.value.code == "invalid_date"
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary("2026-06-25", None)
    assert exc.value.code == "invalid_date"


def test_api_summary_operation_failed_collapses(temp_db, monkeypatch):
    """An unexpected service exception is collapsed to operation_failed."""
    def boom(*args, **kwargs):
        raise RuntimeError("internal boom")
    monkeypatch.setattr(statistics_service, "get_statistics_export_summary", boom)
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert exc.value.code == "operation_failed"


def test_api_summary_no_sensitive_fields_in_error(temp_db, monkeypatch):
    """The error must not echo internal exception details."""
    def boom(*args, **kwargs):
        raise RuntimeError("C:\\secret\\internal.sql boom")
    monkeypatch.setattr(statistics_service, "get_statistics_export_summary", boom)
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert "secret" not in str(exc.value).lower()
    assert "internal" not in str(exc.value).lower()
    assert exc.value.code == "operation_failed"
