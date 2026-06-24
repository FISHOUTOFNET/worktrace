"""Excel and local-data export facade for the UI.

Wraps ``export_service``. ``openpyxl`` is imported lazily inside the service
functions, so importing this module does not load the workbook stack.
"""

from __future__ import annotations

from ..services import export_service


def export_excel(start_date: str, end_date: str, path: str) -> str:
    return export_service.export_excel(start_date, end_date, path)


def export_all_local_data(path: str) -> str:
    return export_service.export_all_local_data(path)


__all__ = ["export_all_local_data", "export_excel"]
