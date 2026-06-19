from __future__ import annotations

import logging
from pathlib import Path

from ..db import get_connection, now_str, reset_database
from ..exports.excel_exporter import export_excel_file
from ..exports.markdown_exporter import export_markdown_file


def export_excel(start_date: str, end_date: str, path: str) -> str:
    try:
        result = export_excel_file(start_date, end_date, path)
        logging.info("excel export success")
        return result
    except Exception:
        logging.exception("excel export error")
        raise


def export_markdown(start_date: str, end_date: str, path: str) -> str:
    try:
        result = export_markdown_file(start_date, end_date, path)
        logging.info("markdown export success")
        return result
    except Exception:
        logging.exception("markdown export error")
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
            "activity_project_assignment",
            "project",
            "resource",
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
    if not confirm:
        raise ValueError("confirmation is required")
    reset_database()
    from .folder_rule_service import invalidate_folder_rule_cache
    from .privacy_service import clear_exclude_keywords_cache
    from .project_inference_service import invalidate_keyword_rule_cache
    from .project_service import invalidate_uncategorized_project_cache
    from .settings_service import clear_settings_cache

    clear_settings_cache()
    clear_exclude_keywords_cache()
    invalidate_uncategorized_project_cache()
    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()
    logging.info("all local data cleared at %s", now_str())
