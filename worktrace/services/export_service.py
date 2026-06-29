from __future__ import annotations

import csv
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..constants import UNCATEGORIZED_PROJECT
from ..db import get_connection, now_str, reset_database
from ..exports.excel_exporter import export_excel_file
from ..formatters import format_duration, format_resource_type, format_safe_display_name
from . import statistics_service, timeline_service

logger = logging.getLogger(__name__)

_UNKNOWN_APP_LABEL = "未知应用"

# Phase 4B: ordered CSV columns. Each entry is ``(dict_key, csv_header)``.
# The dict rows returned by ``build_statistics_csv_rows`` use the English
# keys; the writer emits the Chinese headers so Excel opens the file with
# readable column names. The columns are display-safe by construction:
# raw ``window_title`` / ``file_path_hint`` / ``full_path`` / clipboard /
# note / traceback / SQL are never present in any column.
_CSV_COLUMNS = [
    ("date", "日期"),
    ("start_time", "开始时间"),
    ("end_time", "结束时间"),
    ("duration", "时长"),
    ("duration_seconds", "时长秒数"),
    ("project", "项目"),
    ("app", "应用"),
    ("resource_type", "资源类型"),
    ("resource_name", "资源名称"),
    ("status", "状态"),
]

# Characters that mark a CSV formula injection attempt. A leading single
# quote is prepended so spreadsheet applications treat the cell as text
# instead of evaluating it as a formula. Tab is included because some
# importers treat a leading tab as a formula trigger.
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
    """Build display-safe CSV row dicts for the statistics CSV export.

    Reuses the canonical ``statistics_service.validate_statistics_date_range``
    so the export enforces the exact same date rules as the read-only
    summary (``YYYY-MM-DD``, ``date_from <= date_to``, inclusive span <= 31
    calendar days; ``None`` / ``bool`` / non-string rejected).

    Data source is ``timeline_service.get_report_activity_rows`` with
    ``include_hidden=False`` (hidden excluded) — the report query already
    filters ``is_deleted = 1``. Only closed activities are exported:
    ``is_in_progress`` rows are dropped because they have no finalized
    duration. All statuses (``normal`` / ``idle`` / ``paused`` /
    ``excluded`` / ``error``) are included.

    The returned rows are display-safe: the resource name uses
    ``format_safe_display_name`` (``resource_display_name`` →
    ``activity_display_name`` → ``app_name`` → ``process_name`` → ``未知``)
    and NEVER falls back to the raw ``window_title`` column. Raw
    ``window_title`` / ``file_path_hint`` / ``full_path`` / clipboard /
    ``note`` / traceback / SQL are never placed in any column.

    Raises ``ValueError`` with a stable code token (``invalid_date`` /
    ``invalid_range`` / ``range_too_large``) for invalid date input; this
    is mapped by the API layer to a stable error code.
    """
    statistics_service.validate_statistics_date_range(date_from, date_to)
    rows = timeline_service.get_report_activity_rows(
        date_from,
        date_to,
        include_hidden=False,
        ensure_context=True,
    )
    csv_rows: list[dict] = []
    for row in rows:
        if row.get("is_in_progress"):
            continue
        duration_seconds = int(
            row.get("report_duration_seconds")
            or row.get("duration_seconds")
            or 0
        )
        project_name = str(
            row.get("report_project_name")
            or row.get("display_project_name")
            or UNCATEGORIZED_PROJECT
        ).strip() or UNCATEGORIZED_PROJECT
        app_name = str(row.get("app_name") or "").strip() or _UNKNOWN_APP_LABEL
        csv_rows.append(
            {
                "date": str(row.get("report_date") or ""),
                "start_time": str(row.get("start_time") or ""),
                "end_time": str(row.get("end_time") or ""),
                "duration": format_duration(duration_seconds),
                "duration_seconds": duration_seconds,
                "project": project_name,
                "app": app_name,
                "resource_type": format_resource_type(
                    row.get("resource_kind"),
                    row.get("resource_subtype"),
                ),
                "resource_name": format_safe_display_name(row),
                "status": statistics_service.get_status_display_label(
                    row.get("status")
                ),
            }
        )
    return csv_rows


def write_statistics_csv(date_from: str, date_to: str, output_path) -> dict:
    """Build display-safe CSV rows and write them to ``output_path``.

    Date validation reuses ``statistics_service.validate_statistics_date_range``.
    The output path is normalized to end with ``.csv`` (a missing or
    non-csv suffix is replaced). An empty data range raises
    ``ValueError("empty_data")`` and does NOT create a file. A path that
    points at an existing directory, or whose parent directory does not
    exist, raises ``ValueError("invalid_path")``. ``PermissionError`` and
    other ``OSError`` subclasses are allowed to propagate so the API layer
    can map them to ``permission_denied`` / ``file_busy``.

    The file is written with ``newline=""`` and ``encoding="utf-8-sig"`` so
    Excel detects the UTF-8 BOM and renders Chinese headers correctly. Each
    text cell is passed through ``_escape_csv_cell`` to mitigate CSV
    formula injection.

    Returns ``{"activity_count": int, "duration_seconds": int,
    "filename": str}`` on success. ``filename`` is the basename of the
    written file only (never the full local path).

    This function only writes the chosen CSV file. It never writes to the
    DB, never updates ``activity_log.updated_at``, never opens a folder,
    never opens the exported file, and never auto-submits a timesheet.
    """
    statistics_service.validate_statistics_date_range(date_from, date_to)

    path = Path(output_path)
    # Reject a directory path BEFORE suffix normalization. ``with_suffix``
    # would otherwise turn ``subdir/`` into ``subdir.csv`` and silently
    # hide the directory mistake.
    if path.exists() and path.is_dir():
        raise ValueError("invalid_path")
    # Normalize to a ``.csv`` extension. ``with_suffix`` replaces any
    # existing suffix, so ``report`` -> ``report.csv`` and
    # ``report.txt`` -> ``report.csv``; an existing ``.csv`` is unchanged.
    if path.suffix.lower() != ".csv":
        path = path.with_suffix(".csv")
    # Re-check after suffix normalization in case the new path collides
    # with an existing directory (e.g. user passed ``report.csv/`` on a
    # filesystem that allows it).
    if path.exists() and path.is_dir():
        raise ValueError("invalid_path")
    parent = path.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError("invalid_path")

    csv_rows = build_statistics_csv_rows(date_from, date_to)
    if not csv_rows:
        raise ValueError("empty_data")

    total_seconds = sum(int(row["duration_seconds"]) for row in csv_rows)
    headers = [header for _key, header in _CSV_COLUMNS]
    keys = [key for key, _header in _CSV_COLUMNS]

    # ``newline=""`` is required by the csv module to avoid double ``\r\n``.
    # ``utf-8-sig`` writes a BOM so Excel opens Chinese headers correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in csv_rows:
            writer.writerow([_escape_csv_cell(row.get(key, "")) for key in keys])

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
            "activity_clipboard_event",
            "project",
            "project_session_note",
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
    """Clear all local data by resetting the database.

    Phase 6D hardening: when ``confirm=True`` the reset runs inside a
    destructive reset guard that mirrors the secure-backup import guard
    semantics. While the guard is active the collector is paused and
    ``secure_import_in_progress`` is set to ``true`` so the collector loop
    skips its normal write path (see ``collector.is_secure_import_in_progress``).
    On success the app is left paused so the user can verify the cleared
    state before resuming recording; on failure the prior pause / status
    state is best-effort restored and ``secure_import_in_progress`` is
    cleared so the collector is never permanently blocked.

    This guard is local to ``export_service``; it does NOT reuse the
    private ``secure_backup_service._secure_import_guard`` context manager
    (that would create a cross-service private dependency). The schema and
    ``reset_database`` table-rebuild semantics are unchanged.

    Cache invalidation after a successful reset matches the
    ``secure_backup_service._invalidate_caches`` set: settings cache,
    privacy exclude rules cache, uncategorized project cache, folder rule
    cache, keyword rule cache, and context recompute cache. The context
    recompute cache was previously missing from this path; it is now
    invalidated because ``reset_database`` drops all activity / project /
    rule rows that the context recompute cache is derived from.
    """
    if not confirm:
        raise ValueError("confirmation is required")
    with _destructive_reset_guard():
        reset_database()
    _invalidate_clear_all_caches()
    logging.info("all local data cleared at %s", now_str())


@contextmanager
def _destructive_reset_guard() -> Iterator[None]:
    """Narrow destructive reset guard for ``clear_all_local_data``.

    Mirrors the secure-backup import guard semantics but stays local to
    ``export_service`` so no cross-service private dependency is
    introduced. On enter it rejects if another destructive operation is
    already in progress (``secure_import_in_progress`` true), snapshots
    the current ``user_paused`` / ``collector_status`` /
    ``current_activity_snapshot`` values, then forces them to a safe
    paused state and sets ``secure_import_in_progress=true`` so the
    collector loop skips writes for the duration of the DB replacement.

    On success (no exception escapes the ``with`` block) the app is left
    paused (``user_paused=true`` / ``collector_status=paused`` /
    ``current_activity_snapshot=""``) and ``secure_import_in_progress`` is
    cleared, mirroring the secure-import success semantics so the user
    must manually resume recording after verifying the cleared state.

    On failure (an exception propagates out of the ``with`` block) the
    guard best-effort restores the prior pause / status / snapshot values
    and clears ``secure_import_in_progress`` so the collector is never
    permanently blocked, then re-raises the exception. The exception is
    allowed to propagate so the API facade can collapse it to the stable
    Chinese message.

    Logging records only the operation name and exception type; it never
    records path, clipboard, window title, note, SQL, traceback, or
    payload.
    """
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
    prior_snapshot = get_setting("current_activity_snapshot", "") or ""

    set_setting("user_paused", "true")
    set_setting("collector_status", "paused")
    set_setting("current_activity_snapshot", "")
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
        set_setting("current_activity_snapshot", prior_snapshot)
        set_setting("secure_import_in_progress", "false")
        clear_settings_cache()
        raise
    else:
        # On success leave the app paused so the user can verify the cleared
        # state before resuming recording. ``reset_database`` re-seeds
        # default settings (including user_paused/collector_status), so we
        # explicitly re-assert the paused state here, matching the
        # secure-import success semantics.
        set_setting("user_paused", "true")
        set_setting("collector_status", "paused")
        set_setting("current_activity_snapshot", "")
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
