"""Phase 4B Statistics CSV export tests.

Covers the new controlled write path on the Statistics / Export page:

- ``worktrace.services.export_service.build_statistics_csv_rows``
- ``worktrace.services.export_service.write_statistics_csv``
- ``worktrace.api.export_api.export_statistics_csv``
- ``worktrace.api.export_api.StatisticsExportError``
- ``worktrace.webview_ui.bridge.WebViewBridge.export_statistics_csv``
- ``worktrace.webview_ui.bridge.WebViewBridge._choose_csv_save_path``

Scope covered:

Service / API layer:

- CSV export success: UTF-8 BOM, Chinese headers, correct row count, total duration;
- multi-day range export correct;
- hidden / deleted / in-progress activities are excluded;
- normal / idle / paused / excluded / error statuses are all exported;
- empty data returns ``empty_data`` and creates NO file;
- invalid date / invalid range / range too large reuse the summary rules;
- bool / None / non-string inputs are rejected;
- CSV never contains raw ``window_title`` / ``file_path_hint`` / ``full_path`` /
  clipboard / note / traceback / SQL;
- CSV formula injection is escaped (``=`` / ``+`` / ``-`` / ``@`` / tab);
- permission / file-busy / OSError mapped to stable error codes;
- export writes only the chosen CSV file (no DB write, no ``updated_at``
  mutation, no resource / assignment / session-note side effects);
- missing ``.csv`` suffix is auto-appended; directory / missing-parent
  paths are rejected.

Bridge layer:

- success returns basename only (no full local path);
- cancel save dialog does NOT call the API write;
- invalid date / invalid range / range too large return stable Chinese;
- empty data / permission / file busy / unexpected exception return stable
  Chinese;
- payload never contains traceback / SQL / full path / raw exception /
  window title / file path / note;
- bridge imports only ``worktrace.api`` plus the allowed formatter /
  external UI dialog dependency (no services / db / collector / runtime /
  config / security);
- the existing ``get_statistics_export_summary`` remains read-only (no
  write, no save dialog, no file touch).
"""

from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from worktrace.api import export_api, statistics_api
from worktrace.api.export_api import StatisticsExportError
from worktrace.db import get_connection
from worktrace.services import (
    activity_service,
    export_service,
    project_service,
    settings_service,
    statistics_service,
)
from worktrace.webview_ui.bridge import WebViewBridge


SENSITIVE_TOKENS = (
    "window_title",
    "file_path_hint",
    "full_path",
    "clipboard",
    "top secret",
    "secret note",
    "Traceback",
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
)


def _assert_no_sensitive_text(text: str, label: str = "payload") -> None:
    lowered = text.lower()
    for token in SENSITIVE_TOKENS:
        assert token.lower() not in lowered, (
            f"{label} must not expose sensitive token '{token}'"
        )


def _assert_no_sensitive_keys(payload, label: str = "payload") -> None:
    if isinstance(payload, dict):
        for key in (
            "window_title",
            "file_path_hint",
            "full_path",
            "clipboard",
            "note",
            "traceback",
            "exception",
            "stack",
            "sql",
        ):
            assert key not in payload, (
                f"{label} must not expose sensitive key '{key}'; "
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
    note="top secret note",
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


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    return rows[0], rows[1:]


# --- Service: build_statistics_csv_rows ---------------------------------


def test_build_csv_rows_returns_display_safe_dicts(temp_db):
    pid = project_service.create_project("Client")
    _seed_closed_activity(
        app="Word",
        resource="A1.docx",
        start="09:00:00",
        end="09:30:00",
        day="2026-06-25",
        project_id=pid,
        file_path_hint="C:\\secret\\A1.docx",
        note="top secret note",
    )
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert len(rows) == 1
    row = rows[0]
    expected_keys = {
        "date",
        "start_time",
        "end_time",
        "duration",
        "duration_seconds",
        "project",
        "app",
        "resource_type",
        "resource_name",
        "status",
    }
    assert set(row.keys()) == expected_keys
    assert row["date"] == "2026-06-25"
    assert row["start_time"].startswith("2026-06-25 09:00:00")
    assert row["duration_seconds"] == 1800
    assert row["duration"] == "00:30:00"
    assert row["project"] == "Client"
    assert row["app"] == "Word"
    # resource_name uses the display-safe chain; never the raw window_title
    # or file_path_hint. ``A1.docx`` is the resource kind/subtype label, not
    # the file_path_hint value.
    assert row["resource_name"] != ""
    assert "secret" not in row["resource_name"].lower()
    assert "top secret" not in row["resource_name"].lower()
    # No sensitive raw columns leak through the row dict.
    _assert_no_sensitive_keys(row, "csv row")


def test_build_csv_rows_excludes_in_progress(temp_db):
    """In-progress activities (end_time IS NULL) are not exported."""
    aid = activity_service.create_activity(
        "Word", "winword.exe", "A1.docx",
        start_time="2026-06-25 09:00:00",
        file_path_hint="C:\\secret\\A1.docx",
        note="live note",
    )
    activity_service.finalize_created_activity(aid)
    # NOT closing the activity leaves it in-progress.
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert rows == []


def test_build_csv_rows_excludes_hidden(temp_db):
    """Hidden activities are excluded (include_hidden=False)."""
    aid = _seed_closed_activity(day="2026-06-25")
    from worktrace.api import timeline_api
    timeline_api.hide_timeline_activity(aid)
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert rows == []


def test_build_csv_rows_excludes_deleted(temp_db):
    """Soft-deleted activities are excluded."""
    aid = _seed_closed_activity(day="2026-06-25")
    from worktrace.api import timeline_api
    timeline_api.soft_delete_timeline_activity(aid)
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert rows == []


def test_build_csv_rows_all_statuses_exported(temp_db):
    """normal / idle / paused / excluded / error are all included."""
    statuses = ("normal", "idle", "paused", "excluded", "error")
    starts = [
        "09:00:00", "09:30:00", "10:00:00", "10:30:00", "11:00:00",
    ]
    ends = [
        "09:30:00", "10:00:00", "10:30:00", "11:00:00", "11:30:00",
    ]
    for status, start, end in zip(statuses, starts, ends):
        _seed_closed_activity(
            app=status.title(),
            resource=f"{status}.txt",
            start=start,
            end=end,
            day="2026-06-25",
            status=status,
        )
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert len(rows) == 5
    exported_statuses = sorted(r["status"] for r in rows)
    # All five statuses must be represented (each with a non-empty Chinese label).
    assert len(exported_statuses) == 5
    for status in exported_statuses:
        assert status != ""
        assert status != "未知"


def test_build_csv_rows_multi_day_range(temp_db):
    """Multi-day range exports activities from all included days."""
    _seed_closed_activity(
        resource="day1.txt", start="09:00:00", end="09:30:00", day="2026-06-25",
    )
    _seed_closed_activity(
        resource="day2.txt", start="10:00:00", end="10:15:00", day="2026-06-26",
    )
    _seed_closed_activity(
        resource="day3.txt", start="11:00:00", end="11:45:00", day="2026-06-27",
    )
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-27")
    assert len(rows) == 3
    dates = sorted(r["date"] for r in rows)
    assert dates == ["2026-06-25", "2026-06-26", "2026-06-27"]


def test_build_csv_rows_invalid_date(temp_db):
    with pytest.raises(ValueError):
        export_service.build_statistics_csv_rows("not-a-date", "2026-06-25")


def test_build_csv_rows_invalid_range(temp_db):
    """date_from > date_to is rejected."""
    with pytest.raises(ValueError):
        export_service.build_statistics_csv_rows("2026-06-26", "2026-06-25")


def test_build_csv_rows_range_too_large(temp_db):
    """Range > 31 days is rejected."""
    with pytest.raises(ValueError):
        export_service.build_statistics_csv_rows("2026-05-25", "2026-06-26")


def test_build_csv_rows_bool_rejected(temp_db):
    with pytest.raises(ValueError):
        export_service.build_statistics_csv_rows(True, "2026-06-25")
    with pytest.raises(ValueError):
        export_service.build_statistics_csv_rows("2026-06-25", False)


def test_build_csv_rows_none_rejected(temp_db):
    with pytest.raises(ValueError):
        export_service.build_statistics_csv_rows(None, "2026-06-25")
    with pytest.raises(ValueError):
        export_service.build_statistics_csv_rows("2026-06-25", None)


# --- Service: write_statistics_csv -------------------------------------


def test_write_csv_success_creates_utf8_bom_file(temp_db, tmp_path):
    _seed_closed_activity(
        app="Word", resource="A1.docx",
        start="09:00:00", end="09:30:00", day="2026-06-25",
        file_path_hint="C:\\secret\\A1.docx", note="top secret note",
    )
    out = tmp_path / "report.csv"
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    assert out.exists()
    assert result["activity_count"] == 1
    assert result["duration_seconds"] == 1800
    # filename is the basename only (never the full local path).
    assert result["filename"] == "report.csv"
    # UTF-8 BOM is the first three bytes.
    raw = out.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"
    headers, rows = _read_csv(out)
    assert headers == [
        "日期", "开始时间", "结束时间", "时长", "时长秒数",
        "项目", "应用", "资源类型", "资源名称", "状态",
    ]
    assert len(rows) == 1
    # Total duration matches.
    assert rows[0][4] == "1800"
    assert rows[0][3] == "00:30:00"


def test_write_csv_auto_appends_csv_extension(temp_db, tmp_path):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report"  # no extension
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    written = tmp_path / "report.csv"
    assert written.exists()
    assert result["filename"] == "report.csv"


def test_write_csv_replaces_non_csv_extension(temp_db, tmp_path):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.txt"
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    written = tmp_path / "report.csv"
    assert written.exists()
    assert not (tmp_path / "report.txt").exists()
    assert result["filename"] == "report.csv"


def test_write_csv_empty_data_returns_empty_data_no_file(temp_db, tmp_path):
    out = tmp_path / "empty.csv"
    with pytest.raises(ValueError, match="empty_data"):
        export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    # No file is created for an empty range.
    assert not out.exists()


def test_write_csv_rejects_directory_path(temp_db, tmp_path):
    directory = tmp_path / "subdir"
    directory.mkdir()
    with pytest.raises(ValueError, match="invalid_path"):
        export_service.write_statistics_csv("2026-06-25", "2026-06-25", directory)


def test_write_csv_rejects_missing_parent(temp_db, tmp_path):
    out = tmp_path / "no_such_dir" / "report.csv"
    with pytest.raises(ValueError, match="invalid_path"):
        export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)


def test_write_csv_propagates_permission_error(temp_db, tmp_path):
    """PermissionError surfaces as itself so the API can map it to
    permission_denied; the service does not swallow it as invalid_path."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    # Force open() to raise PermissionError.
    real_open = open

    def fake_open(path, mode, *args, **kwargs):
        if str(path) == str(out):
            raise PermissionError("denied")
        return real_open(path, mode, *args, **kwargs)

    with patch("worktrace.services.export_service.open", fake_open):
        with pytest.raises(PermissionError):
            export_service.write_statistics_csv(
                "2026-06-25", "2026-06-25", out,
            )


def test_write_csv_propagates_oserror(temp_db, tmp_path):
    """OSError surfaces as itself so the API can map it to file_busy."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    real_open = open

    def fake_open(path, mode, *args, **kwargs):
        if str(path) == str(out):
            raise OSError("busy")
        return real_open(path, mode, *args, **kwargs)

    with patch("worktrace.services.export_service.open", fake_open):
        with pytest.raises(OSError):
            export_service.write_statistics_csv(
                "2026-06-25", "2026-06-25", out,
            )


def test_write_csv_no_db_write(temp_db, tmp_path):
    """Export must not mutate the DB: no new rows, no updated_at changes."""
    aid = _seed_closed_activity(day="2026-06-25")
    # Snapshot the activity's updated_at before export.
    with get_connection() as conn:
        before = conn.execute(
            "SELECT updated_at FROM activity_log WHERE id = ?", (aid,),
        ).fetchone()
    assert before is not None
    updated_at_before = before[0]

    out = tmp_path / "report.csv"
    export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)

    # No new activity rows were inserted.
    with get_connection() as conn:
        after = conn.execute(
            "SELECT updated_at FROM activity_log WHERE id = ?", (aid,),
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM activity_log",
        ).fetchone()[0]
    assert after is not None
    assert after[0] == updated_at_before
    assert count == 1


def test_write_csv_no_resource_or_assignment_mutation(temp_db, tmp_path):
    """Export must not mutate activity_resource / assignment rows."""
    pid = project_service.create_project("Client")
    _seed_closed_activity(day="2026-06-25", project_id=pid)
    with get_connection() as conn:
        before_res = conn.execute(
            "SELECT COUNT(*) FROM activity_resource",
        ).fetchone()[0]
        before_asg = conn.execute(
            "SELECT COUNT(*) FROM activity_project_assignment",
        ).fetchone()[0]
        before_note = conn.execute(
            "SELECT COUNT(*) FROM project_session_note",
        ).fetchone()[0]
    out = tmp_path / "report.csv"
    export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    with get_connection() as conn:
        after_res = conn.execute(
            "SELECT COUNT(*) FROM activity_resource",
        ).fetchone()[0]
        after_asg = conn.execute(
            "SELECT COUNT(*) FROM activity_project_assignment",
        ).fetchone()[0]
        after_note = conn.execute(
            "SELECT COUNT(*) FROM project_session_note",
        ).fetchone()[0]
    assert after_res == before_res
    assert after_asg == before_asg
    assert after_note == before_note


def test_write_csv_no_raw_sensitive_fields_in_output(temp_db, tmp_path):
    """The CSV file content must never contain raw window_title /
    file_path_hint / full_path / clipboard / note / traceback / SQL."""
    _seed_closed_activity(
        app="Word", resource="A1.docx",
        start="09:00:00", end="09:30:00", day="2026-06-25",
        file_path_hint="C:\\Users\\secret\\A1.docx",
        note="top secret note",
    )
    out = tmp_path / "report.csv"
    export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    text = out.read_text(encoding="utf-8-sig")
    _assert_no_sensitive_text(text, "csv content")


def test_write_csv_escapes_formula_injection(temp_db, tmp_path):
    """Cells starting with ``=`` / ``+`` / ``-`` / ``@`` / tab get a
    single-quote prefix so spreadsheet apps treat them as text."""
    # Seed an activity whose resource ``display_name`` starts with each
    # dangerous prefix. The ``activity_resource.display_name`` column
    # surfaces in the safe display chain as ``resource_display_name``
    # (the first key tried by ``format_safe_display_name``). We set it
    # directly via SQL so the test isolates the CSV escape behavior from
    # the resource detection layer.
    prefixes = ["=", "+", "-", "@"]
    starts = ["09:00:00", "09:30:00", "10:00:00", "10:30:00"]
    ends = ["09:30:00", "10:00:00", "10:30:00", "11:00:00"]
    for prefix, start, end in zip(prefixes, starts, ends):
        aid = activity_service.create_activity(
            "App", "app.exe", "r.txt",
            start_time=f"2026-06-25 {start}",
            note="top secret note",
            file_path_hint="C:\\secret\\r.txt",
        )
        # Inject a dangerous-prefix display name through the resource row.
        with get_connection() as conn:
            conn.execute(
                "UPDATE activity_resource SET display_name = ? "
                "WHERE activity_id = ?",
                (prefix + "SUM(A1:A2)", aid),
            )
        activity_service.finalize_created_activity(aid)
        activity_service.close_activity(aid, f"2026-06-25 {end}")
    out = tmp_path / "report.csv"
    export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    headers, rows = _read_csv(out)
    assert len(rows) == 4
    # Each resource_name cell must start with the escaped single-quote prefix.
    resource_name_col = headers.index("资源名称")
    for row in rows:
        cell = row[resource_name_col]
        assert cell.startswith("'"), (
            f"formula-injection cell must be escaped with leading quote: {cell!r}"
        )
        # The original dangerous prefix must still be present after the quote.
        assert cell[1:2] in ("=", "+", "-", "@"), (
            f"escaped cell must retain dangerous prefix: {cell!r}"
        )


# --- API layer ---------------------------------------------------------


def test_api_export_success_returns_payload(temp_db, tmp_path):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    result = export_api.export_statistics_csv("2026-06-25", "2026-06-25", out)
    assert result["activity_count"] == 1
    assert result["duration_seconds"] == 1800
    assert result["filename"] == "report.csv"
    assert out.exists()


def test_api_export_invalid_date_raises(temp_db, tmp_path):
    out = tmp_path / "report.csv"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv("not-a-date", "2026-06-25", out)
    assert exc.value.code == "invalid_date"


def test_api_export_invalid_range_raises(temp_db, tmp_path):
    out = tmp_path / "report.csv"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv("2026-06-26", "2026-06-25", out)
    assert exc.value.code == "invalid_range"


def test_api_export_range_too_large_raises(temp_db, tmp_path):
    out = tmp_path / "report.csv"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv("2026-05-25", "2026-06-26", out)
    assert exc.value.code == "range_too_large"


def test_api_export_bool_raises_invalid_date(temp_db, tmp_path):
    out = tmp_path / "report.csv"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv(True, "2026-06-25", out)
    assert exc.value.code == "invalid_date"


def test_api_export_none_raises_invalid_date(temp_db, tmp_path):
    out = tmp_path / "report.csv"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv(None, "2026-06-25", out)
    assert exc.value.code == "invalid_date"


def test_api_export_empty_data_raises(temp_db, tmp_path):
    out = tmp_path / "report.csv"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv("2026-06-25", "2026-06-25", out)
    assert exc.value.code == "empty_data"
    assert not out.exists()


def test_api_export_invalid_path_raises(temp_db, tmp_path):
    _seed_closed_activity(day="2026-06-25")
    directory = tmp_path / "subdir"
    directory.mkdir()
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv("2026-06-25", "2026-06-25", directory)
    assert exc.value.code == "invalid_path"


def test_api_export_missing_parent_raises_invalid_path(temp_db, tmp_path):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "no_such_dir" / "report.csv"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv("2026-06-25", "2026-06-25", out)
    assert exc.value.code == "invalid_path"


def test_api_export_permission_denied_maps_to_stable_code(temp_db, tmp_path):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    with patch(
        "worktrace.services.export_service.open",
        side_effect=PermissionError("denied"),
    ):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", out,
            )
    assert exc.value.code == "permission_denied"


def test_api_export_oserror_maps_to_file_busy(temp_db, tmp_path):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    with patch(
        "worktrace.services.export_service.open",
        side_effect=OSError("busy"),
    ):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", out,
            )
    assert exc.value.code == "file_busy"


def test_api_export_unknown_exception_maps_to_operation_failed(temp_db, tmp_path):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    with patch(
        "worktrace.services.export_service.write_statistics_csv",
        side_effect=RuntimeError("unexpected"),
    ):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", out,
            )
    assert exc.value.code == "operation_failed"


def test_api_export_error_message_never_leaks_internals(temp_db, tmp_path):
    """The StatisticsExportError message must never contain the raw
    exception text, full path, SQL, traceback, or sensitive fields."""
    _seed_closed_activity(
        day="2026-06-25",
        file_path_hint="C:\\Users\\secret\\A1.docx",
        note="top secret note",
    )
    out = tmp_path / "report.csv"
    with patch(
        "worktrace.services.export_service.open",
        side_effect=PermissionError(
            "Traceback (most recent call last): File C:\\secret\\A1.docx "
            "SELECT * FROM activity_log"
        ),
    ):
        try:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", out,
            )
            assert False, "expected StatisticsExportError"
        except StatisticsExportError as exc:
            text = str(exc)
            lowered = text.lower()
            for token in (
                "traceback", "secret", "select", "c:\\", "a1.docx",
                "window_title", "file_path_hint", "note",
            ):
                assert token.lower() not in lowered, (
                    f"error message must not leak '{token}': {text!r}"
                )


# --- Bridge layer ------------------------------------------------------


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    return WebViewBridge()


def _stub_window(save_path: str | None):
    """Return a fake pywebview window whose save dialog returns ``save_path``.

    ``save_path=None`` simulates a user cancel.
    """
    class _FakeWindow:
        def __init__(self, save_path):
            self._save_path = save_path
            self.dialog_calls = 0

        def create_file_dialog(self, *args, **kwargs):
            self.dialog_calls += 1
            if self._save_path is None:
                return None
            return (self._save_path,)

    return _FakeWindow(save_path)


def test_bridge_export_success_returns_basename_only(temp_db, tmp_path, bridge):
    """Success returns only the basename; the full local path never leaves
    the bridge."""
    _seed_closed_activity(
        day="2026-06-25",
        file_path_hint="C:\\Users\\secret\\A1.docx",
        note="top secret note",
    )
    out = tmp_path / "deep" / "nested" / "report.csv"
    out.parent.mkdir(parents=True)
    bridge.set_window(_stub_window(str(out)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    assert result["cancelled"] is False
    assert result["filename"] == "report.csv"
    assert result["activity_count"] == 1
    assert result["duration"] == "00:30:00"
    # The full local path must NOT appear in the returned payload.
    payload_str = str(result)
    assert str(out) not in payload_str
    assert "deep" not in payload_str
    assert "nested" not in payload_str
    _assert_no_sensitive_keys(result)


def test_bridge_export_cancel_does_not_call_api(temp_db, tmp_path, bridge):
    """When the user cancels the save dialog, the bridge returns the clean
    cancel payload and does NOT call the API write."""
    _seed_closed_activity(day="2026-06-25")
    # Use a dedicated output subdir so we can check no CSV was written
    # without colliding with the temp_db fixture's worktrace.db file.
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    bridge.set_window(_stub_window(None))
    with patch(
        "worktrace.webview_ui.bridge_statistics.export_api.export_statistics_csv",
    ) as fake_write:
        result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["error"] == "已取消导出"
    # The API write was NOT called.
    assert fake_write.call_count == 0
    # No CSV file was written to the output dir.
    assert list(out_dir.iterdir()) == []


def test_bridge_export_invalid_date_returns_chinese(temp_db, tmp_path, bridge):
    bridge.set_window(_stub_window(str(tmp_path / "x.csv")))
    result = bridge.export_statistics_csv("not-a-date", "2026-06-25")
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == "请选择有效日期"


def test_bridge_export_invalid_range_returns_chinese(temp_db, tmp_path, bridge):
    bridge.set_window(_stub_window(str(tmp_path / "x.csv")))
    result = bridge.export_statistics_csv("2026-06-26", "2026-06-25")
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == "请选择有效日期范围"


def test_bridge_export_range_too_large_returns_chinese(temp_db, tmp_path, bridge):
    bridge.set_window(_stub_window(str(tmp_path / "x.csv")))
    result = bridge.export_statistics_csv("2026-05-25", "2026-06-26")
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == "日期范围过大"


def test_bridge_export_bool_returns_chinese(temp_db, tmp_path, bridge):
    bridge.set_window(_stub_window(str(tmp_path / "x.csv")))
    result = bridge.export_statistics_csv(True, "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"


def test_bridge_export_none_returns_chinese(temp_db, tmp_path, bridge):
    bridge.set_window(_stub_window(str(tmp_path / "x.csv")))
    result = bridge.export_statistics_csv(None, "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"


def test_bridge_export_empty_data_returns_chinese(temp_db, tmp_path, bridge):
    bridge.set_window(_stub_window(str(tmp_path / "x.csv")))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == "当前范围没有可导出的记录"
    # No file was created.
    assert not (tmp_path / "x.csv").exists()


def test_bridge_export_permission_denied_returns_chinese(temp_db, tmp_path, bridge):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    bridge.set_window(_stub_window(str(out)))
    with patch(
        "worktrace.services.export_service.open",
        side_effect=PermissionError("denied"),
    ):
        result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == "无法写入文件，请检查权限或文件是否被占用"


def test_bridge_export_file_busy_returns_chinese(temp_db, tmp_path, bridge):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    bridge.set_window(_stub_window(str(out)))
    with patch(
        "worktrace.services.export_service.open",
        side_effect=OSError("busy"),
    ):
        result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "无法写入文件，请检查权限或文件是否被占用"


def test_bridge_export_invalid_path_returns_chinese(temp_db, tmp_path, bridge):
    _seed_closed_activity(day="2026-06-25")
    # Point the save dialog at a non-existent parent directory.
    bad = tmp_path / "no_such_dir" / "report.csv"
    bridge.set_window(_stub_window(str(bad)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效保存位置"


def test_bridge_export_unknown_exception_collapses_to_chinese(temp_db, tmp_path, bridge):
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    bridge.set_window(_stub_window(str(out)))
    with patch(
        "worktrace.services.export_service.write_statistics_csv",
        side_effect=RuntimeError("Traceback SELECT FROM C:\\secret"),
    ):
        result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    # The raw exception text must NOT leak through the payload.
    payload_str = str(result)
    lowered = payload_str.lower()
    for token in (
        "traceback", "select", "secret", "c:\\", "runtimeerror",
        "window_title", "file_path_hint", "note",
    ):
        assert token.lower() not in lowered, (
            f"payload must not leak '{token}': {payload_str!r}"
        )


def test_bridge_export_no_window_returns_operation_failed(temp_db, bridge):
    """Without ``set_window``, the save dialog cannot open and the bridge
    collapses to the generic export failure."""
    _seed_closed_activity(day="2026-06-25")
    # No set_window call: self._window stays None.
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "导出失败"


def test_bridge_export_payload_never_contains_full_path(temp_db, tmp_path, bridge):
    """The full local path must never appear in the success payload even
    if the user picks a deeply nested location."""
    _seed_closed_activity(day="2026-06-25")
    nested = tmp_path / "very" / "deep" / "nested" / "report.csv"
    nested.parent.mkdir(parents=True)
    bridge.set_window(_stub_window(str(nested)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    payload_str = str(result)
    assert str(nested) not in payload_str
    assert "very" not in payload_str
    assert "nested" not in payload_str


def test_bridge_export_does_not_import_backend_internals():
    """The WebView bridge modules must import only ``worktrace.api`` (plus
    formatters and the lazily-resolved pywebview UI dependency). They must
    NOT import services / db / collector / runtime / config / security.

    Phase M4: ``bridge.py`` is now a thin composition class; the method
    bodies live in the mixin files (``bridge_common.py``,
    ``bridge_dialogs.py``, ``bridge_overview.py``, ``bridge_settings.py``,
    ``bridge_statistics.py``, ``bridge_timeline.py``, ``bridge_rules.py``).
    All 8 bridge files must satisfy the boundary."""
    import worktrace
    bridge_dir = Path(worktrace.__file__).parent / "webview_ui"
    bridge_files = [
        "bridge.py",
        "bridge_common.py",
        "bridge_dialogs.py",
        "bridge_overview.py",
        "bridge_settings.py",
        "bridge_statistics.py",
        "bridge_timeline.py",
        "bridge_rules.py",
    ]
    for name in bridge_files:
        bridge_path = bridge_dir / name
        assert bridge_path.is_file(), f"missing bridge file: {name}"
        source = bridge_path.read_text(encoding="utf-8")
        for forbidden in (
            "from ..services",
            "from worktrace.services",
            "from ..db",
            "from worktrace.db",
            "from ..collector",
            "from worktrace.collector",
            "from ..security",
            "from worktrace.security",
            "from ..runtime",
            "from worktrace.runtime",
            "from ..config",
            "from worktrace.config",
            "import worktrace.services",
            "import worktrace.db",
            "import worktrace.collector",
            "import worktrace.security",
            "import worktrace.runtime",
            "import worktrace.config",
        ):
            assert forbidden not in source, (
                f"{name} must not import backend internals: {forbidden}"
            )


def test_bridge_get_statistics_export_summary_remains_read_only(temp_db, tmp_path, bridge):
    """The existing read-only summary method must NOT open a save dialog
    or write a file, even with a window injected."""
    _seed_closed_activity(day="2026-06-25")
    window = _stub_window(str(tmp_path / "should_not_be_used.csv"))
    bridge.set_window(window)
    result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    # The save dialog was never opened by the read-only path.
    assert window.dialog_calls == 0
    # No file was written.
    assert not (tmp_path / "should_not_be_used.csv").exists()


def test_bridge_set_window_does_not_start_gui():
    """Importing the bridge and constructing it must not start the GUI."""
    bridge = WebViewBridge()
    assert bridge._window is None
    # set_window itself must not start the GUI either; it just stores the
    # reference pywebview already created.
    bridge.set_window(object())
    assert bridge._window is not None


# --- Bridge: error messages are stable Chinese -------------------------


def test_bridge_export_error_messages_are_stable_chinese():
    """All error codes map to stable Chinese messages; unknown codes
    collapse to '导出失败'."""
    from worktrace.webview_ui.bridge_statistics import _STATISTICS_EXPORT_ERROR_MESSAGES

    expected = {
        "invalid_date": "请选择有效日期",
        "invalid_range": "请选择有效日期范围",
        "range_too_large": "日期范围过大",
        "empty_data": "当前范围没有可导出的记录",
        "invalid_path": "请选择有效保存位置",
        "permission_denied": "无法写入文件，请检查权限或文件是否被占用",
        "file_busy": "无法写入文件，请检查权限或文件是否被占用",
        "write_failed": "无法写入文件，请检查权限或文件是否被占用",
        "operation_failed": "导出失败",
    }
    for code, message in expected.items():
        assert _STATISTICS_EXPORT_ERROR_MESSAGES.get(code) == message, (
            f"error code '{code}' must map to '{message}'"
        )


# --- Phase 4B.1: native save dialog hardening --------------------------
# Precision tests for the pywebview save-dialog return-shape variants and
# the dialog-constant / dialog-exception collapse paths. The bridge must
# handle every documented ``create_file_dialog`` return shape (None, empty
# sequence, single string, sequence of paths) and map every dialog failure
# to the stable ``导出失败`` message without leaking raw exceptions.


class _FakeDialogWindow:
    """Fake pywebview window with a configurable ``create_file_dialog``.

    ``return_value`` is what the dialog returns; ``raise_exc`` (if set) is
    raised instead. ``dialog_calls`` counts invocations so tests can assert
    the dialog was opened exactly once.
    """

    def __init__(self, return_value=None, raise_exc=None):
        self._return_value = return_value
        self._raise_exc = raise_exc
        self.dialog_calls = 0

    def create_file_dialog(self, *args, **kwargs):
        self.dialog_calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._return_value


def test_bridge_export_dialog_returns_single_string(temp_db, tmp_path, bridge):
    """Phase 4B.1: when ``create_file_dialog`` returns a bare string (not
    wrapped in a tuple/list), the bridge must accept it as a valid path."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    bridge.set_window(_FakeDialogWindow(return_value=str(out)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    assert result["cancelled"] is False
    assert result["filename"] == "report.csv"
    assert out.exists()


def test_bridge_export_dialog_returns_empty_tuple(temp_db, tmp_path, bridge):
    """Phase 4B.1: an empty tuple from the dialog is treated as a cancel
    (not as a failure and not as a write attempt)."""
    _seed_closed_activity(day="2026-06-25")
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    bridge.set_window(_FakeDialogWindow(return_value=()))
    with patch(
        "worktrace.webview_ui.bridge_statistics.export_api.export_statistics_csv",
    ) as fake_write:
        result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["error"] == "已取消导出"
    assert fake_write.call_count == 0
    assert list(out_dir.iterdir()) == []


def test_bridge_export_dialog_returns_empty_list(temp_db, tmp_path, bridge):
    """Phase 4B.1: an empty list from the dialog is treated as a cancel."""
    _seed_closed_activity(day="2026-06-25")
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    bridge.set_window(_FakeDialogWindow(return_value=[]))
    with patch(
        "worktrace.webview_ui.bridge_statistics.export_api.export_statistics_csv",
    ) as fake_write:
        result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["error"] == "已取消导出"
    assert fake_write.call_count == 0
    assert list(out_dir.iterdir()) == []


def test_bridge_export_dialog_returns_list_with_path(temp_db, tmp_path, bridge):
    """Phase 4B.1: a list (not just a tuple) containing a path is accepted."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    bridge.set_window(_FakeDialogWindow(return_value=[str(out)]))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    assert result["filename"] == "report.csv"
    assert out.exists()


def test_bridge_export_dialog_raises_exception(temp_db, tmp_path, bridge):
    """Phase 4B.1: when ``create_file_dialog`` raises, the bridge collapses
    to ``导出失败`` and never leaks the raw exception text."""
    _seed_closed_activity(day="2026-06-25")
    bridge.set_window(
        _FakeDialogWindow(raise_exc=RuntimeError("Traceback SELECT C:\\secret"))
    )
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    payload_str = str(result)
    for token in ("traceback", "select", "secret", "c:\\", "runtimeerror"):
        assert token.lower() not in payload_str.lower(), (
            f"dialog-exception payload must not leak '{token}': {payload_str!r}"
        )


def test_bridge_export_dialog_missing_file_dialog_constant(
    temp_db, tmp_path, bridge, monkeypatch
):
    """Phase 4B.1: when the installed pywebview exposes neither
    ``FileDialog.SAVE`` nor the deprecated ``SAVE_DIALOG``, the bridge
    collapses to ``导出失败`` and never opens the dialog."""
    _seed_closed_activity(day="2026-06-25")
    window = _FakeDialogWindow(return_value=str(tmp_path / "x.csv"))
    bridge.set_window(window)

    class _BareWebview:
        """A pywebview shim without FileDialog or SAVE_DIALOG."""

    monkeypatch.setitem(sys.modules, "webview", _BareWebview())
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    # The dialog must NOT have been opened because the constant was missing.
    assert window.dialog_calls == 0


def test_bridge_export_dialog_file_dialog_without_save_constant(
    temp_db, tmp_path, bridge, monkeypatch
):
    """Phase 4B.1: when ``webview.FileDialog`` exists but has no ``SAVE``
    attribute (and no ``SAVE_DIALOG`` fallback), the bridge collapses to
    ``导出失败``."""
    _seed_closed_activity(day="2026-06-25")
    window = _FakeDialogWindow(return_value=str(tmp_path / "x.csv"))
    bridge.set_window(window)

    class _FileDialogNoSave:
        """FileDialog shim that is missing the SAVE constant."""

    class _WebviewNoSave:
        FileDialog = _FileDialogNoSave

    monkeypatch.setitem(sys.modules, "webview", _WebviewNoSave())
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    assert window.dialog_calls == 0


def test_bridge_export_dialog_uses_legacy_save_dialog_fallback(
    temp_db, tmp_path, bridge, monkeypatch
):
    """Phase 4B.1: when ``FileDialog`` is absent but the deprecated
    ``SAVE_DIALOG`` constant exists, the bridge must use it and the export
    must succeed. This locks the documented fallback behavior."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    window = _FakeDialogWindow(return_value=str(out))
    bridge.set_window(window)

    class _LegacyWebview:
        SAVE_DIALOG = 10  # deprecated constant

    monkeypatch.setitem(sys.modules, "webview", _LegacyWebview())
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    assert result["filename"] == "report.csv"
    assert window.dialog_calls == 1
    assert out.exists()


# --- Phase 4B.1: service path-extension hardening ---------------------


def test_write_csv_preserves_uppercase_csv_extension(temp_db, tmp_path):
    """Phase 4B.1: an uppercase ``.CSV`` suffix must be preserved (not
    double-suffixed to ``.CSV.csv``). ``with_suffix`` is only applied when
    the lowercased suffix is not ``.csv``."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.CSV"
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    assert result["filename"] == "report.CSV"
    written = tmp_path / "report.CSV"
    assert written.exists()
    # No double-suffixed file should be created.
    assert not (tmp_path / "report.CSV.csv").exists()


def test_write_csv_preserves_mixed_case_csv_extension(temp_db, tmp_path):
    """Phase 4B.1: a mixed-case ``.Csv`` suffix must also be preserved."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.Csv"
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    assert result["filename"] == "report.Csv"
    assert (tmp_path / "report.Csv").exists()


def test_write_csv_preserves_lowercase_csv_extension(temp_db, tmp_path):
    """Phase 4B.1: an existing lowercase ``.csv`` suffix is unchanged
    (regression lock for the suffix normalization branch)."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.csv"
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", out)
    assert result["filename"] == "report.csv"
    assert out.exists()


def test_api_export_uppercase_csv_extension(temp_db, tmp_path):
    """Phase 4B.1: the API layer must preserve an uppercase ``.CSV`` suffix
    and return it as the basename (no double-suffixing)."""
    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "report.CSV"
    result = export_api.export_statistics_csv("2026-06-25", "2026-06-25", out)
    assert result["filename"] == "report.CSV"
    assert out.exists()


def test_write_csv_chinese_and_space_path(temp_db, tmp_path):
    """Phase 4B.1: a path containing Chinese characters and spaces must be
    written successfully. This locks the Windows Chinese-path / space-path
    write behavior without requiring a real Windows filesystem."""
    _seed_closed_activity(day="2026-06-25")
    nested = tmp_path / "导出 目录" / "报表 文件.csv"
    nested.parent.mkdir(parents=True)
    result = export_service.write_statistics_csv(
        "2026-06-25", "2026-06-25", nested,
    )
    assert result["filename"] == "报表 文件.csv"
    assert nested.exists()
    # The file content must be readable with the UTF-8 BOM.
    headers, rows = _read_csv(nested)
    assert len(rows) == 1
