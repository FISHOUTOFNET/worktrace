from __future__ import annotations

import csv
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..db import get_connection, now_str, reset_database
from ..exports.excel_exporter import export_excel_file
from . import statistics_service
from .runtime_activity_state_service import clear_runtime_activity_state

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


def _escape_csv_cell(value) -> str:
    """Render a cell value as a string and escape CSV formula injection.

    Values starting with ``=`` / ``+`` / ``-`` / ``@`` / tab get a single
    leading quote prepended so Excel / LibreOffice / Google Sheets treat the
    cell as plain text instead of evaluating it as a formula. Non-string
    values are coerced via ``str()``.
    """
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_INJECTION_PREFIXES:
        return "'" + text
    return text


def build_statistics_csv_rows(date_from: str, date_to: str) -> list[dict]:
    """Build display-safe CSV row dicts for the statistics CSV export."""
    statistics_service.validate_statistics_date_range(date_from, date_to)
    from .report_projection_snapshot_service import build_visible_snapshot
    from .statistics_projection import build_statistics_projection

    return build_statistics_projection(build_visible_snapshot(date_from, date_to, ensure_context=True)).export_rows


def write_statistics_csv(date_from: str, date_to: str, output_path, expected_snapshot_revision: str | None = None) -> dict:
    """Build display-safe CSV rows and write them to ``output_path``."""
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

    projection = build_statistics_projection(build_visible_snapshot(date_from, date_to, ensure_context=True))
    if expected_snapshot_revision is not None and str(expected_snapshot_revision or "") != projection.snapshot_revision:
        raise ValueError("stale_statistics_snapshot")
    csv_rows = projection.export_rows
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
        "activity_count": len(csv_rows),
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


def export_all_local_data(path: str) -> str:
    from openpyxl import Workbook

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    default = wb.active
    wb.remove(default)
    with get_connection() as conn:
        for table in [
            "activity_log",
            "activity_resource",
            "activity_project_assignment",
            "report_session_operation",
            "report_session_operation_member",
            "report_session_operation_dependency",
            "activity_clipboard_event",
            "project",
            "folder_project_rule",
            "project_rule",
            "settings",
        ]:
            ws = wb.create_sheet(table)
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            columns = [item["name"] for item in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            ws.append(columns)
            for row in rows:
                ws.append([row[col] for col in columns])
    wb.save(out)
    logging.info("all local data export success")
    return str(out)


def clear_all_local_data(confirm: bool) -> None:
    """Clear all local data by resetting the database."""
    if not confirm:
        raise ValueError("confirmation is required")
    with _destructive_reset_guard():
        reset_database()
    _invalidate_clear_all_caches()
    logging.info("all local data cleared at %s", now_str())


@contextmanager
def _destructive_reset_guard() -> Iterator[None]:
    """Narrow destructive reset guard for ``clear_all_local_data``."""
    from ..services.settings_service import (
        clear_settings_cache,
        get_bool_setting,
        get_setting,
        set_setting,
    )

    if get_bool_setting("secure_import_in_progress", False):
        logging.warning("clear-all rejected: destructive operation in progress")
        raise ValueError("operation_in_progress")

    prior_user_paused = get_bool_setting("user_paused", False)
    prior_collector_status = get_setting("collector_status", "stopped") or "stopped"
    from ..collector.snapshot_publisher import DEFAULT_SNAPSHOT_PUBLISHER

    prior_snapshot = DEFAULT_SNAPSHOT_PUBLISHER.read_raw()

    set_setting("user_paused", "true")
    set_setting("collector_status", "paused")
    clear_runtime_activity_state("clear_all_guard_enter")
    set_setting("secure_import_in_progress", "true")
    clear_settings_cache()

    try:
        yield
    except Exception as exc:
        # Restore prior state on failure. Do not log the exception message:
        # it may carry sensitive details from upstream layers. Only log the
        # exception type so internal details stay out of the log file.
        logging.warning(
            "clear-all destructive reset failed exc_type=%s", type(exc).__name__
        )
        set_setting("user_paused", "true" if prior_user_paused else "false")
        set_setting("collector_status", prior_collector_status)
        DEFAULT_SNAPSHOT_PUBLISHER.restore_raw(prior_snapshot)
        set_setting("secure_import_in_progress", "false")
        clear_settings_cache()
        raise
    else:
        # On success leave the app paused so the user can verify the cleared
        # state before resuming. reset_database re-seeds defaults, so we
        # re-assert the paused state here, matching secure-import semantics.
        set_setting("user_paused", "true")
        set_setting("collector_status", "paused")
        clear_runtime_activity_state("clear_all_success")
        set_setting("secure_import_in_progress", "false")
        clear_settings_cache()
        logging.info("clear-all destructive reset guard completed paused=true")


def _invalidate_clear_all_caches() -> None:
    """Invalidate service-layer caches after a clear-all reset.

    Mirrors the ``secure_backup_service._invalidate_caches`` set so the
    clear-all path invalidates the same caches a successful encrypted
    backup import does. The context recompute cache is included because
    ``reset_database`` drops all activity / project / rule rows that the
    context recompute cache is derived from; leaving it stale would let
    the user see pre-clear context on the next Timeline / Statistics
    load.
    """
    from .context_service import invalidate_context_recompute_cache
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
    invalidate_context_recompute_cache()
