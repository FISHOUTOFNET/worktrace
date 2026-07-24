from __future__ import annotations

import csv
import errno
import logging
import os
from pathlib import Path

from ..atomic_file import (
    AtomicFileOutput,
    AtomicReplaceError,
    TemporaryFileCleanupError,
    TemporaryFileError,
)
from ..db import get_connection, now_str
from ..exports.excel_exporter import export_excel_file
from . import statistics_service
from .statistics_scope_policy import normalize_statistics_project_scope

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
    {"folder_rule_index_state", "folder_rule_file_index"}
)


class ExportFileError(OSError):
    """Stable, path-free export infrastructure error."""

    def __init__(self, code: str) -> None:
        normalized = str(code or "operation_failed")
        super().__init__(normalized)
        self.code = normalized


def classify_export_os_error(exc: BaseException) -> str:
    if isinstance(exc, TemporaryFileCleanupError):
        return "cleanup_failed"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    winerror = getattr(exc, "winerror", None)
    if winerror in {32, 33}:
        return "file_busy"
    error_number = getattr(exc, "errno", None)
    if error_number in {errno.EBUSY, getattr(errno, "ETXTBSY", errno.EBUSY)}:
        return "file_busy"
    if error_number in {
        errno.ENOENT,
        errno.ENOTDIR,
        errno.EISDIR,
        errno.EINVAL,
        getattr(errno, "ENAMETOOLONG", errno.EINVAL),
    }:
        return "invalid_path"
    if error_number in {
        errno.ENOSPC,
        getattr(errno, "EDQUOT", errno.ENOSPC),
        errno.EROFS,
        errno.EIO,
        getattr(errno, "ENODEV", errno.EIO),
    }:
        return "storage_unavailable"
    if isinstance(exc, (AtomicReplaceError, TemporaryFileError)):
        return "write_failed"
    if isinstance(exc, OSError):
        # Raw destination-open failures without a platform code cannot prove a
        # storage or path cause. Treat them as an unavailable/locked target;
        # canonical write and replace owners provide explicit write_failed codes.
        return "file_busy"
    return "operation_failed"


def _raise_export_file_error(exc: BaseException, *, stage: str) -> None:
    code = classify_export_os_error(exc)
    logger.warning(
        "export failed stage=%s code=%s exception=%s",
        str(stage or "write"),
        code,
        type(exc).__name__,
    )
    raise ExportFileError(code) from exc


def _escape_csv_cell(value) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_INJECTION_PREFIXES:
        return "'" + text
    return text


def build_statistics_csv_rows(date_from: str, date_to: str) -> list[dict]:
    from .report_projection_snapshot_service import build_visible_snapshot
    from .statistics_projection import iter_statistics_export_records

    statistics_service.validate_statistics_date_range(date_from, date_to)
    snapshot = build_visible_snapshot(date_from, date_to)
    return list(iter_statistics_export_records(snapshot))


def write_statistics_csv(
    date_from: str,
    date_to: str,
    output_path,
    expected_export_ticket_revision: str,
    project_id: str | int | None = None,
) -> dict:
    """Write the exact accepted closed-record projection to CSV.

    Builds exactly one canonical snapshot and uses it for both the export
    ticket validation and the CSV record iteration so that the checked state
    and the written state are the same object. Records are streamed row by
    row instead of being fully materialised in memory.
    """

    date_from, date_to = statistics_service.resolve_statistics_date_range(date_from, date_to)
    statistics_service.validate_statistics_project_scope(project_id)
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
    from .statistics_projection import (
        build_statistics_summary_projection,
        iter_statistics_export_records,
    )

    snapshot = build_visible_snapshot(date_from, date_to)
    summary_projection = build_statistics_summary_projection(
        snapshot, project_id=project_id
    )
    normalized_scope = normalize_statistics_project_scope(project_id)
    current_ticket = statistics_service.compute_statistics_export_ticket_revision(
        summary_projection.snapshot_revision,
        date_from,
        date_to,
        normalized_scope,
    )
    if str(expected_export_ticket_revision or "") != current_ticket:
        raise ValueError("stale_statistics_snapshot")

    headers = [header for _key, header in _CSV_COLUMNS]
    keys = [key for key, _header in _CSV_COLUMNS]
    row_count = 0
    total_seconds = 0
    try:
        with AtomicFileOutput(path, resource="statistics_csv") as output:
            with open(
                output.temporary_path,
                "w",
                newline="",
                encoding="utf-8-sig",
            ) as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                for row in iter_statistics_export_records(
                    snapshot, project_id=project_id
                ):
                    writer.writerow(
                        [_escape_csv_cell(row.get(key, "")) for key in keys]
                    )
                    row_count += 1
                    total_seconds += int(row.get("duration_seconds") or 0)
                if row_count == 0:
                    raise ValueError("empty_data")
                handle.flush()
                os.fsync(handle.fileno())
            output.commit()
    except PermissionError:
        # Preserve the explicit infrastructure type for service callers. The API
        # boundary converts it to the stable permission_denied code.
        raise
    except (OSError, TemporaryFileError) as exc:
        _raise_export_file_error(exc, stage="statistics_csv")
    return {
        "activity_count": summary_projection.activity_count,
        "export_row_count": row_count,
        "duration_seconds": total_seconds,
        "filename": path.name,
    }


def export_excel(start_date: str, end_date: str, path: str) -> str:
    try:
        result = export_excel_file(start_date, end_date, path)
        logging.info("excel export success")
        return result
    except PermissionError:
        raise
    except (OSError, TemporaryFileError) as exc:
        _raise_export_file_error(exc, stage="excel")
    except Exception as exc:
        logger.warning(
            "excel export failed stage=render exception=%s",
            type(exc).__name__,
        )
        raise


def _local_data_export_tables() -> tuple[str, ...]:
    from .secure_backup_service import EXPORT_TABLES

    return tuple(
        table for table in EXPORT_TABLES if table not in _DERIVED_RUNTIME_TABLES
    )


def export_all_local_data(path: str) -> str:
    from openpyxl import Workbook

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)
    with get_connection() as conn:
        conn.execute("BEGIN")
        try:
            for table in _local_data_export_tables():
                worksheet = workbook.create_sheet(table)
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                columns = [
                    item["name"]
                    for item in conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                ]
                worksheet.append(columns)
                for row in rows:
                    worksheet.append([row[column] for column in columns])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    try:
        with AtomicFileOutput(out, resource="local_data_export") as output:
            workbook.save(output.temporary_path)
            output.commit()
    except PermissionError:
        raise
    except (OSError, TemporaryFileError) as exc:
        _raise_export_file_error(exc, stage="local_data")
    logging.info("all local data export success")
    return str(out)


def clear_all_local_data(confirm: bool) -> None:
    if not confirm:
        raise ValueError("confirmation is required")
    from .database_maintenance_service import (
        MaintenanceInProgressError,
        clear_all_live_data,
    )

    try:
        clear_all_live_data()
    except MaintenanceInProgressError as exc:
        raise ValueError("operation_in_progress") from exc
    logging.info("all local data cleared at %s", now_str())


__all__ = [
    "ExportFileError",
    "build_statistics_csv_rows",
    "classify_export_os_error",
    "clear_all_local_data",
    "export_all_local_data",
    "export_excel",
    "write_statistics_csv",
]
