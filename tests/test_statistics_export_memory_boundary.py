from __future__ import annotations

import csv
from dataclasses import fields
from pathlib import Path

import pytest

from worktrace.services import export_service

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


def test_prepared_statistics_csv_export_retains_only_final_rows():
    field_names = {field.name for field in fields(export_service.PreparedStatisticsCsvExport)}
    assert field_names == {
        "rows",
        "activity_count",
        "export_row_count",
        "duration_seconds",
    }
    assert "snapshot" not in field_names
    assert "range_projection" not in field_names
    assert "project_id" not in field_names


def test_prepared_statistics_csv_writer_is_projection_free(tmp_path, monkeypatch):
    prepared = export_service.PreparedStatisticsCsvExport(
        rows=(
            export_service.PreparedStatisticsCsvRow(
                date="2026-08-27",
                start_time="2026-08-27 09:00:00",
                duration="00:30:00",
                project="Client",
                note="",
                duration_seconds=1800,
            ),
        ),
        activity_count=1,
        export_row_count=1,
        duration_seconds=1800,
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("prepared writer must not reread projection/runtime")

    monkeypatch.setattr(export_service.statistics_service, "resolve_statistics_date_range", forbidden)
    monkeypatch.setattr(export_service.statistics_service, "validate_statistics_project_scope", forbidden)

    output = tmp_path / "prepared.csv"
    result = export_service.write_prepared_statistics_csv(prepared, output)

    assert result["activity_count"] == 1
    assert result["export_row_count"] == 1
    assert result["duration_seconds"] == 1800
    with open(output, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "日期": "2026-08-27",
            "开始时间": "2026-08-27 09:00:00",
            "时长": "00:30:00",
            "项目": "Client",
            "备注": "",
        }
    ]


def test_prepare_statistics_csv_has_no_full_range_as_of_owner():
    source = Path(export_service.__file__).read_text(encoding="utf-8")
    prepare_start = source.index("def prepare_statistics_csv(")
    write_start = source.index("def write_prepared_statistics_csv(")
    prepare_source = source[prepare_start:write_start]

    assert "get_statistics_range_projection" in prepare_source
    assert "build_statistics_realtime_overlay" in prepare_source
    assert "build_statistics_as_of_snapshot" not in prepare_source
    assert "build_visible_snapshot" not in prepare_source
    assert "snapshot=" not in prepare_source
