"""Statistics CSV export tests."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.support import activity_factory as activity_service
from tests.support.application import FakeStatisticsCapability, build_test_bridge
from worktrace.api import export_api
from worktrace.api.export_api import StatisticsExportError
from worktrace.db import get_connection
from worktrace.services import (
    export_service,
    project_service,
    settings_service,
    timeline_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]

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
        rows = list(csv.reader(handle))
    return rows[0], rows[1:]


def _summarize(temp_db, date_from: str, date_to: str) -> dict:
    """Return the canonical statistics/export summary for assertions."""
    from worktrace.services import statistics_service

    return statistics_service.get_statistics_export_summary(date_from, date_to)


def _valid_ticket(date_from: str, date_to: str, project_id=None) -> str:
    """Compute a valid export ticket for the given date range and scope."""
    from worktrace.services import statistics_service

    return statistics_service.get_statistics_export_summary(
        date_from, date_to, project_id
    )["ticket_revision"]


def _assert_projection_contract(
    summary: dict,
    *,
    activity_count: int,
    session_count: int,
    export_row_count: int,
    duration_seconds: int,
) -> None:
    """Assert the four semantic counters maintain their current-only meaning."""
    assert summary["activity_count"] == activity_count, (
        f"activity_count expected {activity_count}, got {summary['activity_count']}"
    )
    assert summary["session_count"] == session_count, (
        f"session_count expected {session_count}, got {summary['session_count']}"
    )
    assert summary["export_row_count"] == export_row_count, (
        f"export_row_count expected {export_row_count}, "
        f"got {summary['export_row_count']}"
    )
    assert summary["total_duration_seconds"] == duration_seconds, (
        f"total_duration_seconds expected {duration_seconds}, "
        f"got {summary['total_duration_seconds']}"
    )
    assert summary["export_preview"]["session_count"] == session_count, (
        "export_preview.session_count must mirror top-level session_count"
    )
    assert summary["export_preview"]["export_row_count"] == export_row_count, (
        "export_preview.export_row_count must mirror top-level export_row_count"
    )
    assert (
        summary["export_preview"]["included_activity_count"] == activity_count
    ), (
        "export_preview.included_activity_count must mirror top-level "
        "activity_count"
    )


def test_projection_empty_data_contract(temp_db):
    """Scenario: empty range — all counters are zero and no rows are produced."""
    summary = _summarize(temp_db, "2026-06-27", "2026-06-27")
    _assert_projection_contract(
        summary,
        activity_count=0,
        session_count=0,
        export_row_count=0,
        duration_seconds=0,
    )
    rows = export_service.build_statistics_csv_rows("2026-06-27", "2026-06-27")
    assert rows == []
    assert summary["by_project"] == []
    assert summary["by_app"] == []
    assert summary["by_status"] == []


def test_projection_one_to_one_contract(temp_db):
    """Scenario: one closed activity produces one session and one export row."""
    pid = project_service.create_project("Client")
    _seed_closed_activity(
        day="2026-06-25",
        project_id=pid,
        app="Word",
        start="09:00:00",
        end="09:30:00",
    )
    summary = _summarize(temp_db, "2026-06-25", "2026-06-25")
    _assert_projection_contract(
        summary,
        activity_count=1,
        session_count=1,
        export_row_count=1,
        duration_seconds=1800,
    )
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert len(rows) == 1
    assert rows[0]["duration_seconds"] == 1800


def test_projection_two_activities_aggregated_to_one_row(temp_db):
    """Scenario: two contiguous closed activities (normal then idle) collapse
    into a single report session/export row while activity_count stays 2."""
    pid = project_service.create_project("Aggregator")
    _seed_closed_activity(
        day="2026-06-25",
        project_id=pid,
        app="Word",
        resource="normal.docx",
        start="09:00:00",
        end="09:30:00",
        status="normal",
    )
    _seed_closed_activity(
        day="2026-06-25",
        project_id=pid,
        app="Idle",
        process="idle.exe",
        resource="idle.docx",
        start="09:30:00",
        end="10:00:00",
        status="idle",
    )
    summary = _summarize(temp_db, "2026-06-25", "2026-06-25")
    _assert_projection_contract(
        summary,
        activity_count=2,
        session_count=1,
        export_row_count=1,
        duration_seconds=3600,
    )
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert len(rows) == 1
    assert rows[0]["duration_seconds"] == 3600
    assert rows[0]["start_time"].endswith("09:00:00")
    assert rows[0]["end_time"].endswith("10:00:00")


def test_projection_single_activity_split_across_days(temp_db):
    """Scenario: one activity crossing midnight is split into two report
    slices / export rows, while activity_count stays 1."""
    pid = project_service.create_project("CrossDay")
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "cross.docx",
        start_time="2026-06-25 23:00:00",
        project_id=pid,
        file_path_hint="C:\\secret\\cross.docx",
        note="note",
        status="normal",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-26 01:00:00")
    summary = _summarize(temp_db, "2026-06-25", "2026-06-26")
    _assert_projection_contract(
        summary,
        activity_count=1,
        session_count=2,
        export_row_count=2,
        duration_seconds=7200,
    )
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-26")
    assert len(rows) == 2
    by_date = {row["date"]: row for row in rows}
    assert sorted(by_date) == ["2026-06-25", "2026-06-26"]
    assert by_date["2026-06-25"]["duration_seconds"] == 3600
    assert by_date["2026-06-26"]["duration_seconds"] == 3600
    assert by_date["2026-06-25"]["start_time"].endswith("23:00:00")
    assert by_date["2026-06-26"]["end_time"].endswith("01:00:00")


def test_projection_filtered_activities_keep_accurate_counts(temp_db):
    """Scenario: hidden and in-progress activities are excluded from every
    counter while still-closed visible activities remain accounted for."""
    pid = project_service.create_project("Filtered")
    visible_id = _seed_closed_activity(
        day="2026-06-25",
        project_id=pid,
        app="Word",
        resource="visible.docx",
        start="09:00:00",
        end="09:30:00",
        status="normal",
    )
    hidden_id = _seed_closed_activity(
        day="2026-06-25",
        project_id=pid,
        app="Word",
        resource="hidden.docx",
        start="10:00:00",
        end="10:30:00",
        status="normal",
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?", (hidden_id,)
        )
    in_progress_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "inprog.docx",
        start_time="2026-06-25 11:00:00",
        project_id=pid,
        file_path_hint="C:\\secret\\inprog.docx",
        note="note",
        status="normal",
    )
    activity_service.finalize_created_activity(in_progress_id)
    assert visible_id != hidden_id != in_progress_id
    summary = _summarize(temp_db, "2026-06-25", "2026-06-25")
    _assert_projection_contract(
        summary,
        activity_count=1,
        session_count=1,
        export_row_count=1,
        duration_seconds=1800,
    )
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert len(rows) == 1
    assert rows[0]["start_time"].endswith("09:00:00")


def test_projection_all_statuses_paused_excluded_and_aggregated(temp_db):
    """Scenario: five contiguous closed activities of every official status
    collapse into two aggregated export rows while paused is excluded from
    every counter (activity_count == 4)."""
    pid = project_service.create_project("AllStatuses")
    statuses = ("normal", "idle", "paused", "excluded", "error")
    starts = ("09:00:00", "09:30:00", "10:00:00", "10:30:00", "11:00:00")
    ends = ("09:30:00", "10:00:00", "10:30:00", "11:00:00", "11:30:00")
    for status, start, end in zip(statuses, starts, ends):
        _seed_closed_activity(
            day="2026-06-26",
            project_id=pid,
            app=status.title(),
            process=f"{status}.exe",
            resource=f"{status}.txt",
            start=start,
            end=end,
            status=status,
        )
    summary = _summarize(temp_db, "2026-06-26", "2026-06-26")
    _assert_projection_contract(
        summary,
        activity_count=4,
        session_count=2,
        export_row_count=2,
        duration_seconds=7200,
    )
    rows = export_service.build_statistics_csv_rows("2026-06-26", "2026-06-26")
    assert len(rows) == 2
    by_start = {row["start_time"][-8:]: row for row in rows}
    assert "正常" in by_start["09:00:00"]["status"]
    assert "空闲" in by_start["09:00:00"]["status"]
    assert "已排除" in by_start["10:30:00"]["status"]
    assert "异常" in by_start["10:30:00"]["status"]
    assert "10:00:00" not in by_start  # paused is dropped


def test_build_csv_rows_returns_display_safe_dicts(temp_db):
    pid = project_service.create_project("Client")
    _seed_closed_activity(project_id=pid, file_path_hint="C:\\secret\\A1.docx")
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {
        "date",
        "start_time",
        "end_time",
        "duration",
        "duration_seconds",
        "project",
        "status",
        "note",
        "adjusted_duration",
        "is_adjusted",
    }
    assert row["date"] == "2026-06-25"
    assert row["start_time"].startswith("2026-06-25 09:00:00")
    assert row["duration_seconds"] == 1800
    assert row["duration"] == "00:30:00"
    assert row["project"] == "Client"
    assert row["note"] == ""
    assert row["adjusted_duration"] == ""
    assert row["is_adjusted"] == "否"
    for key in ("window_title", "file_path_hint", "full_path", "clipboard", "traceback", "sql"):
        assert key not in row


def test_build_csv_rows_excludes_in_progress(temp_db):
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "A1.docx",
        start_time="2026-06-25 09:00:00",
        file_path_hint="C:\\secret\\A1.docx",
        note="live note",
    )
    activity_service.finalize_created_activity(aid)
    assert export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25") == []


def test_build_csv_rows_excludes_hidden(temp_db):
    aid = _seed_closed_activity()
    with get_connection() as conn:
        conn.execute("UPDATE activity_log SET is_hidden = 1 WHERE id = ?", (aid,))
    assert export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25") == []


def test_build_csv_rows_excludes_deleted(temp_db):
    aid = _seed_closed_activity()
    with get_connection() as conn:
        conn.execute("UPDATE activity_log SET is_deleted = 1 WHERE id = ?", (aid,))
    assert export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25") == []


def test_build_csv_rows_all_statuses_exported(temp_db):
    pid = project_service.create_project("Client")
    statuses = ("normal", "idle", "paused", "excluded", "error")
    starts = ("09:00:00", "09:30:00", "10:00:00", "10:30:00", "11:00:00")
    ends = ("09:30:00", "10:00:00", "10:30:00", "11:00:00", "11:30:00")
    for status, start, end in zip(statuses, starts, ends):
        _seed_closed_activity(
            app=status.title(),
            resource=f"{status}.txt",
            start=start,
            end=end,
            project_id=pid,
            status=status,
        )
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")
    assert len(rows) == 2
    by_start = {row["start_time"][-8:]: row for row in rows}
    assert "正常" in by_start["09:00:00"]["status"]
    assert "空闲" in by_start["09:00:00"]["status"]
    assert by_start["09:00:00"]["project"] == "Client"
    assert "已排除" in by_start["10:30:00"]["status"]
    assert by_start["10:30:00"]["project"] == "Client"


def test_build_csv_rows_multi_day_range(temp_db):
    _seed_closed_activity(resource="day1.txt", day="2026-06-25")
    _seed_closed_activity(resource="day2.txt", start="10:00:00", end="10:15:00", day="2026-06-26")
    _seed_closed_activity(resource="day3.txt", start="11:00:00", end="11:45:00", day="2026-06-27")
    rows = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-27")
    assert len(rows) == 3
    assert sorted(row["date"] for row in rows) == [
        "2026-06-25",
        "2026-06-26",
        "2026-06-27",
    ]


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [
        ("not-a-date", "2026-06-25"),
        ("2026-06-26", "2026-06-25"),
        (True, "2026-06-25"),
        ("2026-06-25", False),
        (None, "2026-06-25"),
        ("2026-06-25", None),
    ],
)
def test_build_csv_rows_rejects_invalid_ranges(temp_db, date_from, date_to):
    with pytest.raises(ValueError):
        export_service.build_statistics_csv_rows(date_from, date_to)


def test_write_csv_success_creates_utf8_bom_file(temp_db, tmp_path):
    _seed_closed_activity(file_path_hint="C:\\secret\\A1.docx")
    out = tmp_path / "report.csv"
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))
    assert out.exists()
    assert result == {
        "activity_count": 1,
        "export_row_count": 1,
        "duration_seconds": 1800,
        "filename": "report.csv",
    }
    assert out.read_bytes()[:3] == b"\xef\xbb\xbf"
    headers, rows = _read_csv(out)
    assert headers == [
        "日期",
        "开始时间",
        "结束时间",
        "时长",
        "时长秒数",
        "项目",
        "状态",
        "备注",
        "修正时长",
        "是否已修正",
    ]
    assert len(rows) == 1
    assert rows[0][4] == "1800"
    assert rows[0][3] == "00:30:00"


def test_write_csv_auto_appends_csv_extension(temp_db, tmp_path):
    _seed_closed_activity()
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", tmp_path / "report", _valid_ticket("2026-06-25", "2026-06-25"))
    assert (tmp_path / "report.csv").exists()
    assert result["filename"] == "report.csv"


def test_write_csv_replaces_non_csv_extension(temp_db, tmp_path):
    _seed_closed_activity()
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", tmp_path / "report.txt", _valid_ticket("2026-06-25", "2026-06-25"))
    assert (tmp_path / "report.csv").exists()
    assert not (tmp_path / "report.txt").exists()
    assert result["filename"] == "report.csv"


def test_write_csv_empty_data_returns_empty_data_no_file(temp_db, tmp_path):
    out = tmp_path / "empty.csv"
    with pytest.raises(ValueError, match="empty_data"):
        export_service.write_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))
    assert not out.exists()


def test_write_csv_rejects_directory_path(temp_db, tmp_path):
    directory = tmp_path / "subdir"
    directory.mkdir()
    with pytest.raises(ValueError, match="invalid_path"):
        export_service.write_statistics_csv("2026-06-25", "2026-06-25", directory, _valid_ticket("2026-06-25", "2026-06-25"))


def test_write_csv_rejects_missing_parent(temp_db, tmp_path):
    with pytest.raises(ValueError, match="invalid_path"):
        export_service.write_statistics_csv(
            "2026-06-25", "2026-06-25", tmp_path / "missing" / "report.csv",
            _valid_ticket("2026-06-25", "2026-06-25"),
        )


def _matches_atomic_temp_path(path, target: Path) -> bool:
    """Match the unique unpredictable temp file AtomicFileOutput creates.

    AtomicFileOutput uses prefix `.{target.name}.` and suffix `.tmp` inside the
    target's parent directory. The middle segment is a random mkstemp token, so
    tests must match by parent + prefix + suffix rather than a fixed name.
    """
    candidate = Path(path)
    return (
        candidate.parent == target.parent
        and candidate.name.startswith(f".{target.name}.")
        and candidate.name.endswith(".tmp")
    )


def test_write_csv_propagates_permission_error(temp_db, tmp_path):
    _seed_closed_activity()
    out = tmp_path / "report.csv"
    real_open = open

    def fake_open(path, mode, *args, **kwargs):
        if _matches_atomic_temp_path(path, out):
            raise PermissionError("denied")
        return real_open(path, mode, *args, **kwargs)

    with patch("worktrace.services.export_service.open", fake_open):
        with pytest.raises(PermissionError):
            export_service.write_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))


def test_write_csv_propagates_oserror(temp_db, tmp_path):
    _seed_closed_activity()
    out = tmp_path / "report.csv"
    real_open = open

    def fake_open(path, mode, *args, **kwargs):
        if _matches_atomic_temp_path(path, out):
            raise OSError("busy")
        return real_open(path, mode, *args, **kwargs)

    with patch("worktrace.services.export_service.open", fake_open):
        with pytest.raises(OSError):
            export_service.write_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))


def test_write_csv_no_db_write(temp_db, tmp_path):
    aid = _seed_closed_activity()
    with get_connection() as conn:
        updated_at_before = conn.execute(
            "SELECT updated_at FROM activity_log WHERE id = ?", (aid,)
        ).fetchone()[0]
    export_service.write_statistics_csv("2026-06-25", "2026-06-25", tmp_path / "report.csv", _valid_ticket("2026-06-25", "2026-06-25"))
    with get_connection() as conn:
        after = conn.execute(
            "SELECT updated_at FROM activity_log WHERE id = ?", (aid,)
        ).fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
    assert after == updated_at_before
    assert count == 1


def test_write_csv_no_resource_or_assignment_mutation(temp_db, tmp_path):
    pid = project_service.create_project("Client")
    _seed_closed_activity(project_id=pid)
    with get_connection() as conn:
        before = tuple(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "activity_resource",
                "activity_project_assignment",
                "report_session_operation",
            )
        )
    export_service.write_statistics_csv("2026-06-25", "2026-06-25", tmp_path / "report.csv", _valid_ticket("2026-06-25", "2026-06-25"))
    with get_connection() as conn:
        after = tuple(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "activity_resource",
                "activity_project_assignment",
                "report_session_operation",
            )
        )
    assert after == before


def test_write_csv_no_raw_sensitive_fields_in_output(temp_db, tmp_path):
    _seed_closed_activity(file_path_hint="C:\\Users\\secret\\A1.docx")
    out = tmp_path / "report.csv"
    export_service.write_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))
    _assert_no_sensitive_text(out.read_text(encoding="utf-8-sig"), "csv content")


def test_write_csv_escapes_formula_injection(temp_db, tmp_path):
    from worktrace.api import timeline_api

    prefixes = ["=", "+", "-", "@"]
    starts = ["09:00:00", "09:30:00", "10:00:00", "10:30:00"]
    ends = ["09:30:00", "10:00:00", "10:30:00", "11:00:00"]
    for index, (prefix, start, end) in enumerate(zip(prefixes, starts, ends), start=1):
        project_id = project_service.create_project(f"CSV Formula {index}")
        aid = activity_service.create_activity(
            "App",
            "app.exe",
            "r.txt",
            start_time=f"2026-06-25 {start}",
            project_id=project_id,
            note="top secret note",
            file_path_hint="C:\\secret\\r.txt",
        )
        activity_service.finalize_created_activity(aid)
        activity_service.close_activity(aid, f"2026-06-25 {end}")
        session = next(
            item
            for item in timeline_service.get_project_sessions_by_date("2026-06-25")
            if aid in item["activity_ids"]
        )
        timeline_api.save_timeline_session_edit(
            "2026-06-25",
            session["projection_instance_key"],
            session["projection_revision"],
            f"req-formula-{index}",
            None,
            None,
            prefix + "SUM(A1:A2)",
        )
    out = tmp_path / "report.csv"
    export_service.write_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))
    headers, rows = _read_csv(out)
    assert len(rows) == 4
    assert "资源名称" not in headers
    note_column = headers.index("备注")
    for cell in [row[note_column] for row in rows]:
        assert cell.startswith("'")
        assert cell[1:2] in ("=", "+", "-", "@")


def test_api_export_success_returns_payload(temp_db, tmp_path):
    _seed_closed_activity()
    out = tmp_path / "report.csv"
    result = export_api.export_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["activity_count"] == 1
    assert result["duration_seconds"] == 1800
    assert result["filename"] == "report.csv"
    assert out.exists()


@pytest.mark.parametrize(
    ("date_from", "date_to", "code"),
    [
        ("not-a-date", "2026-06-25", "invalid_date"),
        ("2026-06-26", "2026-06-25", "invalid_range"),
        (True, "2026-06-25", "invalid_date"),
        (None, "2026-06-25", "invalid_date"),
    ],
)
def test_api_export_rejects_invalid_inputs(temp_db, tmp_path, date_from, date_to, code):
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv(date_from, date_to, tmp_path / "report.csv", "ignored")
    assert exc.value.code == code


def test_api_export_empty_data_raises(temp_db, tmp_path):
    out = tmp_path / "report.csv"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))
    assert exc.value.code == "empty_data"
    assert not out.exists()


def test_api_export_invalid_paths_raise(temp_db, tmp_path):
    _seed_closed_activity()
    directory = tmp_path / "subdir"
    directory.mkdir()
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv("2026-06-25", "2026-06-25", directory, _valid_ticket("2026-06-25", "2026-06-25"))
    assert exc.value.code == "invalid_path"
    with pytest.raises(StatisticsExportError) as exc:
        export_api.export_statistics_csv(
            "2026-06-25", "2026-06-25", tmp_path / "missing" / "report.csv",
            _valid_ticket("2026-06-25", "2026-06-25"),
        )
    assert exc.value.code == "invalid_path"


@pytest.mark.parametrize(
    ("exception", "code"),
    [(PermissionError("denied"), "permission_denied"), (OSError("busy"), "file_busy")],
)
def test_api_export_maps_file_errors(temp_db, tmp_path, exception, code):
    _seed_closed_activity()
    with patch("worktrace.services.export_service.open", side_effect=exception):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", tmp_path / "report.csv",
                _valid_ticket("2026-06-25", "2026-06-25"),
            )
    assert exc.value.code == code


def test_api_export_unknown_exception_maps_to_operation_failed(temp_db, tmp_path):
    _seed_closed_activity()
    with patch(
        "worktrace.services.export_service.write_statistics_csv",
        side_effect=RuntimeError("unexpected"),
    ):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", tmp_path / "report.csv",
                "ignored",
            )
    assert exc.value.code == "operation_failed"


def test_api_export_error_message_never_leaks_internals(temp_db, tmp_path):
    _seed_closed_activity(file_path_hint="C:\\Users\\secret\\A1.docx")
    with patch(
        "worktrace.services.export_service.open",
        side_effect=PermissionError(
            "Traceback (most recent call last): File C:\\secret\\A1.docx SELECT * FROM activity_log"
        ),
    ):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", tmp_path / "report.csv",
                _valid_ticket("2026-06-25", "2026-06-25"),
            )
    lowered = str(exc.value).lower()
    for token in (
        "traceback",
        "secret",
        "select",
        "c:\\",
        "a1.docx",
        "window_title",
        "file_path_hint",
        "note",
    ):
        assert token.lower() not in lowered


@pytest.fixture()
def bridge(temp_db):
    settings_service.clear_settings_cache()
    return build_test_bridge()


def _stub_window(save_path: str | None):
    class _FakeWindow:
        def __init__(self, value):
            self._save_path = value
            self.dialog_calls = 0

        def create_file_dialog(self, *args, **kwargs):
            self.dialog_calls += 1
            return None if self._save_path is None else (self._save_path,)

    return _FakeWindow(save_path)


def test_bridge_export_success_returns_basename_only(temp_db, tmp_path, bridge):
    _seed_closed_activity(file_path_hint="C:\\Users\\secret\\A1.docx")
    out = tmp_path / "deep" / "nested" / "report.csv"
    out.parent.mkdir(parents=True)
    bridge.set_window(_stub_window(str(out)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is True
    assert result["cancelled"] is False
    assert result["filename"] == "report.csv"
    assert result["activity_count"] == 1
    assert result["duration"] == "00:30:00"
    assert str(out) not in str(result)
    assert "deep" not in str(result)
    assert "nested" not in str(result)
    _assert_no_sensitive_keys(result)


def test_bridge_export_cancel_does_not_call_api(temp_db, tmp_path):
    _seed_closed_activity()
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_stub_window(None))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", "valid-ticket")
    assert result == {"ok": False, "cancelled": True, "error": "已取消导出"}
    assert statistics.export_statistics_csv_calls == []
    assert list(out_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("date_from", "date_to", "message"),
    [
        ("not-a-date", "2026-06-25", "请选择有效日期"),
        ("2026-06-26", "2026-06-25", "请选择有效日期范围"),
        (True, "2026-06-25", "请选择有效日期"),
        (None, "2026-06-25", "请选择有效日期"),
    ],
)
def test_bridge_export_invalid_inputs_return_chinese(
    temp_db, tmp_path, bridge, date_from, date_to, message
):
    bridge.set_window(_stub_window(str(tmp_path / "x.csv")))
    result = bridge.export_statistics_csv(date_from, date_to, "valid-ticket")
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == message


def test_bridge_export_empty_data_returns_chinese(temp_db, tmp_path, bridge):
    out = tmp_path / "x.csv"
    bridge.set_window(_stub_window(str(out)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == "当前范围没有可导出的记录"
    assert not out.exists()


@pytest.mark.parametrize(
    ("exception", "message"),
    [
        (PermissionError("denied"), "导出失败，请检查保存位置和权限"),
        (OSError("busy"), "文件可能被占用，请关闭后重试"),
    ],
)
def test_bridge_export_file_errors_return_chinese(
    temp_db, tmp_path, bridge, exception, message
):
    _seed_closed_activity()
    bridge.set_window(_stub_window(str(tmp_path / "report.csv")))
    with patch("worktrace.services.export_service.open", side_effect=exception):
        result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == message


def test_bridge_export_invalid_path_returns_chinese(temp_db, tmp_path, bridge):
    _seed_closed_activity()
    bridge.set_window(_stub_window(str(tmp_path / "missing" / "report.csv")))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is False
    assert result["error"] == "请选择有效保存位置"


def test_bridge_export_unknown_exception_collapses_to_chinese(temp_db, tmp_path, bridge):
    _seed_closed_activity()
    bridge.set_window(_stub_window(str(tmp_path / "report.csv")))
    with patch(
        "worktrace.services.export_service.write_statistics_csv",
        side_effect=RuntimeError("Traceback SELECT FROM C:\\secret"),
    ):
        result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    lowered = str(result).lower()
    for token in (
        "traceback",
        "select",
        "secret",
        "c:\\",
        "runtimeerror",
        "window_title",
        "file_path_hint",
        "note",
    ):
        assert token.lower() not in lowered


def test_bridge_export_no_window_returns_operation_failed(temp_db, bridge):
    _seed_closed_activity()
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is False
    assert result["error"] == "导出失败"


def test_bridge_export_payload_never_contains_full_path(temp_db, tmp_path, bridge):
    _seed_closed_activity()
    nested = tmp_path / "very" / "deep" / "nested" / "report.csv"
    nested.parent.mkdir(parents=True)
    bridge.set_window(_stub_window(str(nested)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is True
    assert str(nested) not in str(result)
    assert "very" not in str(result)
    assert "nested" not in str(result)


def test_bridge_export_does_not_import_backend_internals():
    import worktrace

    bridge_dir = Path(worktrace.__file__).parent / "webview_ui"
    for name in (
        "bridge.py",
        "bridge_common.py",
        "bridge_dialogs.py",
        "bridge_overview.py",
        "bridge_settings.py",
        "bridge_statistics.py",
        "bridge_timeline.py",
        "bridge_rules.py",
    ):
        source = (bridge_dir / name).read_text(encoding="utf-8")
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
            assert forbidden not in source


def test_bridge_get_statistics_export_summary_remains_read_only(temp_db, tmp_path, bridge):
    _seed_closed_activity()
    window = _stub_window(str(tmp_path / "should_not_be_used.csv"))
    bridge.set_window(window)
    result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    assert window.dialog_calls == 0
    assert not (tmp_path / "should_not_be_used.csv").exists()


def test_bridge_set_window_does_not_start_gui(temp_db):
    bridge = build_test_bridge()
    assert bridge._window is None
    bridge.set_window(object())
    assert bridge._window is not None


def test_bridge_export_error_messages_are_stable_chinese():
    from worktrace.webview_ui.bridge_statistics import _STATISTICS_EXPORT_ERROR_MESSAGES

    expected = {
        "invalid_date": "请选择有效日期",
        "invalid_range": "请选择有效日期范围",
        "range_too_large": "日期范围过大",
        "empty_data": "当前范围没有可导出的记录",
        "invalid_path": "请选择有效保存位置",
        "permission_denied": "导出失败，请检查保存位置和权限",
        "file_busy": "文件可能被占用，请关闭后重试",
        "storage_unavailable": "存储空间或设备不可用",
        "cleanup_failed": "导出未完成，临时文件清理失败",
        "stale_statistics_snapshot": "统计数据已更新，请重新加载后导出",
        "write_failed": "导出失败，请检查保存位置和权限",
        "operation_failed": "导出失败",
    }
    for code, message in expected.items():
        assert _STATISTICS_EXPORT_ERROR_MESSAGES.get(code) == message


class _FakeDialogWindow:
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
    _seed_closed_activity()
    out = tmp_path / "report.csv"
    bridge.set_window(_FakeDialogWindow(return_value=str(out)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is True
    assert result["cancelled"] is False
    assert result["filename"] == "report.csv"
    assert out.exists()


@pytest.mark.parametrize("return_value", [(), []])
def test_bridge_export_dialog_empty_sequence_is_cancelled(
    temp_db, tmp_path, return_value
):
    _seed_closed_activity()
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_FakeDialogWindow(return_value=return_value))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", "valid-ticket")
    assert result == {"ok": False, "cancelled": True, "error": "已取消导出"}
    assert statistics.export_statistics_csv_calls == []
    assert list(out_dir.iterdir()) == []


def test_bridge_export_dialog_returns_list_with_path(temp_db, tmp_path, bridge):
    _seed_closed_activity()
    out = tmp_path / "report.csv"
    bridge.set_window(_FakeDialogWindow(return_value=[str(out)]))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is True
    assert result["filename"] == "report.csv"
    assert out.exists()


def test_bridge_export_dialog_raises_exception(temp_db, bridge):
    _seed_closed_activity()
    bridge.set_window(
        _FakeDialogWindow(raise_exc=RuntimeError("Traceback SELECT C:\\secret"))
    )
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    lowered = str(result).lower()
    for token in ("traceback", "select", "secret", "c:\\", "runtimeerror"):
        assert token not in lowered


def test_bridge_export_dialog_missing_file_dialog_constant(
    temp_db, tmp_path, bridge, monkeypatch
):
    _seed_closed_activity()
    window = _FakeDialogWindow(return_value=str(tmp_path / "x.csv"))
    bridge.set_window(window)

    class _BareWebview:
        pass

    monkeypatch.setitem(sys.modules, "webview", _BareWebview())
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    assert window.dialog_calls == 0


def test_bridge_export_dialog_file_dialog_without_save_constant(
    temp_db, tmp_path, bridge, monkeypatch
):
    _seed_closed_activity()
    window = _FakeDialogWindow(return_value=str(tmp_path / "x.csv"))
    bridge.set_window(window)

    class _FileDialogNoSave:
        pass

    class _WebviewNoSave:
        FileDialog = _FileDialogNoSave

    monkeypatch.setitem(sys.modules, "webview", _WebviewNoSave())
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    assert window.dialog_calls == 0


def test_bridge_export_dialog_uses_deprecated_save_dialog_fallback(
    temp_db, tmp_path, bridge, monkeypatch
):
    _seed_closed_activity()
    out = tmp_path / "report.csv"
    window = _FakeDialogWindow(return_value=str(out))
    bridge.set_window(window)

    class _LegacyWebview:
        SAVE_DIALOG = 10

    monkeypatch.setitem(sys.modules, "webview", _LegacyWebview())
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["ok"] is True
    assert result["filename"] == "report.csv"
    assert window.dialog_calls == 1
    assert out.exists()


@pytest.mark.parametrize("suffix", [".CSV", ".Csv", ".csv"])
def test_write_csv_preserves_csv_extension_case(temp_db, tmp_path, suffix):
    _seed_closed_activity()
    out = tmp_path / f"report{suffix}"
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["filename"] == f"report{suffix}"
    assert out.exists()
    assert not (tmp_path / f"report{suffix}.csv").exists()


def test_api_export_uppercase_csv_extension(temp_db, tmp_path):
    _seed_closed_activity()
    out = tmp_path / "report.CSV"
    result = export_api.export_statistics_csv("2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["filename"] == "report.CSV"
    assert out.exists()


def test_write_csv_chinese_and_space_path(temp_db, tmp_path):
    _seed_closed_activity()
    nested = tmp_path / "导出 目录" / "报表 文件.csv"
    nested.parent.mkdir(parents=True)
    result = export_service.write_statistics_csv("2026-06-25", "2026-06-25", nested, _valid_ticket("2026-06-25", "2026-06-25"))
    assert result["filename"] == "报表 文件.csv"
    assert nested.exists()
    _, rows = _read_csv(nested)
    assert len(rows) == 1


# -- Single-snapshot and streaming contract tests ----------------------------


def test_single_export_builds_one_snapshot(temp_db, tmp_path):
    """One CSV export must call ``build_visible_snapshot`` exactly once."""

    _seed_closed_activity()
    out = tmp_path / "report.csv"
    from worktrace.services import report_projection_snapshot_service as snapshots

    # Compute the ticket BEFORE installing the counting wrapper so the wrapper
    # only observes calls made inside write_statistics_csv itself.
    ticket = _valid_ticket("2026-06-25", "2026-06-25")
    original = snapshots.build_visible_snapshot
    call_count = 0

    def counting_wrapper(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original(*args, **kwargs)

    with patch.object(snapshots, "build_visible_snapshot", counting_wrapper):
        export_service.write_statistics_csv(
            "2026-06-25", "2026-06-25", out, ticket
        )
    assert call_count == 1


def test_ticket_failure_does_not_create_temp_file(temp_db, tmp_path):
    """A stale ticket must not create the target file or any temp residue."""

    _seed_closed_activity()
    out = tmp_path / "stale.csv"
    with pytest.raises(ValueError, match="stale_statistics_snapshot"):
        export_service.write_statistics_csv(
            "2026-06-25", "2026-06-25", out, "wrong-ticket-revision"
        )
    assert not out.exists()
    temp_files = list(tmp_path.glob("*.tmp")) + list(
        tmp_path.glob(f".{out.name}.*")
    )
    assert not temp_files


def test_ticket_failure_does_not_iterate_records(temp_db, tmp_path):
    """A stale ticket must not call the export record iterator."""

    _seed_closed_activity()
    out = tmp_path / "no_iter.csv"
    # iter_statistics_export_records is imported lazily from statistics_projection
    # inside write_statistics_csv, so patch it at its source module.
    with patch(
        "worktrace.services.statistics_projection.iter_statistics_export_records"
    ) as mock_iter:
        mock_iter.return_value = []
        with pytest.raises(ValueError, match="stale_statistics_snapshot"):
            export_service.write_statistics_csv(
                "2026-06-25", "2026-06-25", out, "wrong-ticket"
            )
        assert mock_iter.call_count == 0


def test_zero_records_no_target_file_or_temp(temp_db, tmp_path):
    """Zero records must not leave a target file or temp residue."""

    out = tmp_path / "empty.csv"
    ticket = _valid_ticket("2026-06-25", "2026-06-25")
    with pytest.raises(ValueError, match="empty_data"):
        export_service.write_statistics_csv("2026-06-25", "2026-06-25", out, ticket)
    assert not out.exists()
    temp_files = list(tmp_path.glob("*.tmp")) + list(
        tmp_path.glob(f".{out.name}.*")
    )
    assert not temp_files


def test_streaming_write_returns_correct_counts(temp_db, tmp_path):
    """Streaming write returns correct row count and total duration."""

    _seed_closed_activity(start="09:00:00", end="09:30:00")
    _seed_closed_activity(
        resource="B.docx", start="10:00:00", end="10:15:00"
    )
    out = tmp_path / "stream.csv"
    result = export_service.write_statistics_csv(
        "2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25")
    )
    assert result["export_row_count"] == 2
    assert result["duration_seconds"] == 1800 + 900


def test_csv_formula_injection_still_protected(temp_db, tmp_path):
    """Formula injection protection remains effective after streaming change."""

    from worktrace.api import timeline_api

    aid = activity_service.create_activity(
        "App",
        "app.exe",
        "r.txt",
        start_time="2026-06-25 09:00:00",
        note="top secret note",
        file_path_hint="C:\\secret\\r.txt",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-25 09:30:00")
    session = next(
        item
        for item in timeline_service.get_project_sessions_by_date("2026-06-25")
        if aid in item["activity_ids"]
    )
    timeline_api.save_timeline_session_edit(
        "2026-06-25",
        session["projection_instance_key"],
        session["projection_revision"],
        "req-formula-stream",
        None,
        None,
        "=SUM(A1:A2)",
    )
    out = tmp_path / "formula.csv"
    export_service.write_statistics_csv(
        "2026-06-25", "2026-06-25", out, _valid_ticket("2026-06-25", "2026-06-25")
    )
    headers, rows = _read_csv(out)
    note_column = headers.index("备注")
    assert rows[0][note_column].startswith("'")
    assert rows[0][note_column][1:2] == "="


def test_all_time_export_with_valid_ticket_succeeds(temp_db, tmp_path):
    """All-time export with a valid all-time ticket succeeds and includes data."""

    _seed_closed_activity(day="2026-06-25")
    out = tmp_path / "all_time.csv"
    ticket = _valid_ticket("", "")
    result = export_service.write_statistics_csv("", "", out, ticket)
    assert result["export_row_count"] == 1
    assert out.exists()


# -- Bridge ticket validation tests ------------------------------------------


def test_bridge_export_none_ticket_does_not_open_dialog(temp_db, tmp_path, bridge):
    """A missing (None) ticket must not open the save dialog."""

    _seed_closed_activity()
    window = _FakeDialogWindow(return_value=str(tmp_path / "x.csv"))
    bridge.set_window(window)
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", None)
    assert result["ok"] is False
    assert result["error"] == "统计数据已更新，请重新加载后导出"
    assert window.dialog_calls == 0


def test_bridge_export_empty_string_ticket_does_not_open_dialog(
    temp_db, tmp_path, bridge
):
    """An empty-string ticket must not open the save dialog."""

    _seed_closed_activity()
    window = _FakeDialogWindow(return_value=str(tmp_path / "x.csv"))
    bridge.set_window(window)
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", "")
    assert result["ok"] is False
    assert result["error"] == "统计数据已更新，请重新加载后导出"
    assert window.dialog_calls == 0


def test_bridge_export_whitespace_ticket_does_not_open_dialog(
    temp_db, tmp_path, bridge
):
    """A whitespace-only ticket must not open the save dialog."""

    _seed_closed_activity()
    window = _FakeDialogWindow(return_value=str(tmp_path / "x.csv"))
    bridge.set_window(window)
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", "   ")
    assert result["ok"] is False
    assert result["error"] == "统计数据已更新，请重新加载后导出"
    assert window.dialog_calls == 0


def test_bridge_export_wrong_ticket_rejected_by_service(temp_db, tmp_path, bridge):
    """A syntactically valid but semantically wrong ticket is rejected."""

    _seed_closed_activity()
    out = tmp_path / "wrong.csv"
    bridge.set_window(_FakeDialogWindow(return_value=str(out)))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", "wrong-revision")
    assert result["ok"] is False
    assert result["error"] == "统计数据已更新，请重新加载后导出"
    assert not out.exists()


def test_bridge_export_missing_ticket_does_not_call_service(temp_db, tmp_path):
    """A missing ticket must not call the export service at all."""

    _seed_closed_activity()
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_FakeDialogWindow(return_value=str(tmp_path / "x.csv")))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", None)
    assert result["ok"] is False
    assert statistics.export_statistics_csv_calls == []


def test_wrong_date_range_ticket_rejected(temp_db, tmp_path):
    """A ticket issued for one date range must not export a different range."""

    _seed_closed_activity(day="2026-06-25")
    _seed_closed_activity(day="2026-06-26", start="10:00:00", end="10:30:00")
    june_25_ticket = _valid_ticket("2026-06-25", "2026-06-25")
    out = tmp_path / "wrong_range.csv"
    with pytest.raises(ValueError, match="stale_statistics_snapshot"):
        export_service.write_statistics_csv(
            "2026-06-26", "2026-06-26", out, june_25_ticket
        )
    assert not out.exists()
