from __future__ import annotations

import logging
from pathlib import Path

from openpyxl import Workbook

from ..db import get_connection, now_str, reset_database
from ..exports.excel_exporter import export_excel_file
from ..exports.markdown_exporter import export_markdown_file


def export_excel(start_date: str, end_date: str, path: str) -> str:
    try:
        result = export_excel_file(start_date, end_date, path)
        logging.info("excel export success path=%s", result)
        return result
    except Exception:
        logging.exception("excel export error")
        raise


def export_markdown(start_date: str, end_date: str, path: str) -> str:
    try:
        result = export_markdown_file(start_date, end_date, path)
        logging.info("markdown export success path=%s", result)
        return result
    except Exception:
        logging.exception("markdown export error")
        raise


def export_all_local_data(path: str) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    default = wb.active
    wb.remove(default)
    with get_connection() as conn:
        for table in ["activity_log", "project", "rule", "settings"]:
            ws = wb.create_sheet(table)
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            columns = [item["name"] for item in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            ws.append(columns)
            for row in rows:
                ws.append([row[col] for col in columns])
    wb.save(out)
    logging.info("all local data export success path=%s", out)
    return str(out)


def clear_all_local_data(confirm: bool) -> None:
    if not confirm:
        raise ValueError("confirmation is required")
    reset_database()
    logging.info("all local data cleared at %s", now_str())
