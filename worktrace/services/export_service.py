from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

from ..db import get_connection, now_str
from ..exports.excel_exporter import export_excel_file
from . import statistics_service

logger = logging.getLogger(__name__)

_CSV_COLUMNS = [
    ("date", "日期"),
    ("start_time", "开始时间"),
    ("end_time", "结束时间"),
    ("duration", "时长"),
    ("duration_seconds", "时长秒数"),
    ("project", "项目"),
    ("status", "状态"),
    ("note", "备注"),
    ("adjusted_duration", "修正时长"),
    ("is_adjusted", "是否已修正"),
]

_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t")
_DERIVED_RUNTIME_TABLES = frozenset(
    {
        "folder_rule_index_state",
        "folder_rule_file_index",
    }
)


def _escape_csv_cell(value) -> str:
    """Render a cell value as text and escape spreadsheet formula injection."""
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_INJECTION_PREFIXES:
        return "'" + text
    return text


def build_statistics_csv_rows(date_from: str, date_to: str) -> list[dict]:
    """Build display-safe CSV row dicts for the statistics CSV export."""
    statistics_service.validate_statistics_date_range(date_from, date_to)
    from .report_projection_snapshot_service import build_visible_snapshot
    from .statistics_projection import build_statistics_projection

    return list(
        build_statistics_projection(
            build_visible_snapshot(date_from, date_to)
        ).export_records
    )


def write_statistics_csv(
    date_from: str,
    date_to: str,
    output_path,
    expected_snapshot_revision: str | None = None,
) -> dict:
    """Build display-safe CSV rows and write them to ``output_path``.

    ``expected_snapshot_revision`` is retained as a public compatibility name,
    but its value now represents the export-only revision. Natural growth of an
    open activity therefore cannot invalidate an export containing closed rows.
    """
    statistics_service.validate_statistics_date_range(date_from, date_to)

    path = Path(output_path)
    if path.exists() and path.is_dir():
        raise ValueError("invalid_path")
    if path.suffix.lower() != ".csv":
        path = path.with_suffix(".csv")
    if path.exists() and path.is_dir():
        raise ValueError("invalid_path")
    parent = path.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError("invalid_path")

    from .report_projection_snapshot_service import build_visible_snapshot
    from .statistics_projection import build_statistics_projection

    projection = build_statistics_projection(
        build_visible_snapshot(date_from, date_to)
    )
    if (
        expected_snapshot_revision is not None
        and str(expected_snapshot_revision or "") != projection.export_revision
    ):
        raise ValueError("stale_statistics_snapshot")
    csv_rows = projection.export_records
    if not csv_rows:
        raise ValueError("empty_data")

    total_seconds = sum(int(row["duration_seconds"]) for row in csv_rows)
    headers = [header for _key, header in _CSV_COLUMNS]
    keys = [key for key, _header in _CSV_COLUMNS]

    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in csv_rows:
            writer.writerow([_escape_csv_cell(row.get(key, "")) for key in keys])
    os.replace(tmp_path, path)

    return {
        "activity_count": projection.activity_count,
        "export_row_count": len(csv_rows),
        "duration_seconds": total_seconds,
        "filename": path.name,
    }


def export_excel(start_date: str, end_date: str, path: str) -> str:
    try:
        result = export_excel_file(start_date, end_date, path)
        logging.info("excel export success")
        return result
    except Exception:
        logging.exception("excel export error")
        raise


def _local_data_export_tables() -> tuple[str, ...]:
    """Return user fact/config tables, excluding rebuildable runtime indexes."""
    from .secure_backup_service import EXPORT_TABLES

    return tuple(
        table
        for table in EXPORT_TABLES
        if table not in _DERIVED_RUNTIME_TABLES
    )


def export_all_local_data(path: str) -> str:
    """Export a consistent user-data snapshot under one read transaction."""
    from openpyxl import Workbook

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    default = wb.active
    wb.remove(default)
    with get_connection() as conn:
        conn.execute("BEGIN")
        try:
            for table in _local_data_export_tables():
                ws = wb.create_sheet(table)
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                columns = [
                    item["name"]
                    for item in conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                ]
                ws.append(columns)
                for row in rows:
                    ws.append([row[col] for col in columns])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    wb.save(out)
    logging.info("all local data export success")
    return str(out)


def clear_all_local_data(confirm: bool) -> None:
    """Clear local data atomically through the maintenance coordinator."""
    if not confirm:
        raise ValueError("confirmation is required")
    from .database_maintenance_service import clear_all_live_data
    from .secure_backup_service import (
        BackupImportInProgressError,
        SECURE_IMPORT_COORDINATOR,
    )

    try:
        with SECURE_IMPORT_COORDINATOR.acquire(reason="clear_all") as guard:
            clear_all_live_data()
            guard.mark_succeeded()
    except BackupImportInProgressError as exc:
        raise ValueError("operation_in_progress") from exc
    _invalidate_clear_all_caches()
    logging.info("all local data cleared at %s", now_str())


def _invalidate_clear_all_caches() -> None:
    """Invalidate every cache derived from the replaced database generation."""
    from .folder_rule_service import invalidate_folder_rule_cache
    from .privacy_service import clear_exclude_rules_cache
    from .project_inference_service import invalidate_keyword_rule_cache
    from .project_service import invalidate_uncategorized_project_cache
    from .settings_service import clear_settings_cache

    clear_settings_cache()
    clear_exclude_rules_cache()
    invalidate_uncategorized_project_cache()
    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()
