"""Excel and local-data export facade for the UI.

Wraps ``export_service``. ``openpyxl`` is imported lazily inside the service
functions, so importing this module does not load the workbook stack.

``export_statistics_csv`` is the controlled CSV write path for the
Statistics / Export page. It converts service-layer ``ValueError`` codes
and ``OSError`` / ``PermissionError`` into stable ``StatisticsExportError``
codes so the WebView bridge can map them to Chinese messages without
echoing tracebacks, paths, SQL, or raw exception messages.
"""

from __future__ import annotations

from typing import Any

from ..services import export_service


class StatisticsExportError(ValueError):
    """Raised by the statistics CSV export for known user-facing failures.

    The ``code`` attribute is a stable token the WebView bridge maps to a
    Chinese message, so internal paths, field names, ids, and SQL details
    never enter bridge responses.

    Stable ``code`` values:

    - ``invalid_date`` — ``date_from`` / ``date_to`` is not a valid
      ``YYYY-MM-DD`` string (``None`` / ``bool`` / non-string rejected).
    - ``invalid_range`` — ``date_from`` is after ``date_to``.
    - ``range_too_large`` — the inclusive span exceeds
      ``STATISTICS_SUMMARY_MAX_RANGE_DAYS`` calendar days.
    - ``empty_data`` — the selected range has no closed activities to
      export (no file is created).
    - ``invalid_path`` — the save path is a directory or its parent
      directory does not exist.
    - ``permission_denied`` — the file cannot be written because the
      location is not writable.
    - ``file_busy`` — the file is busy / locked or another ``OSError``
      occurred during the write.
    - ``operation_failed`` — race condition or unexpected service failure.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# Service-layer ``ValueError`` code tokens that map 1:1 to stable export
# error codes. Any other ``ValueError`` text collapses to
# ``operation_failed`` so internal details never reach the bridge.
_EXPORT_VALUE_ERROR_CODES = {
    "invalid_date",
    "invalid_range",
    "range_too_large",
    "empty_data",
    "invalid_path",
}


def export_statistics_csv(date_from: str, date_to: str, output_path) -> dict[str, Any]:
    """Export a display-safe CSV for the statistics date range.

    Delegates date validation, row building, and file writing to
    ``export_service.write_statistics_csv``. The service raises
    ``ValueError`` with a stable code token for date / empty-data / path
    failures; ``PermissionError`` and other ``OSError`` subclasses
    propagate for the API to map.

    On success returns ``{"activity_count": int, "duration_seconds": int,
    "filename": str}`` where ``filename`` is the basename only (never the
    full local path). On failure raises ``StatisticsExportError`` with a
    stable ``code``.

    Never writes to the DB, never opens a folder, never opens the exported
    file, and never surfaces tracebacks, SQL, full paths, raw exception
    text, window titles, file paths, or notes.
    """
    try:
        return export_service.write_statistics_csv(date_from, date_to, output_path)
    except StatisticsExportError:
        raise
    except ValueError as exc:
        code = str(exc)
        if code in _EXPORT_VALUE_ERROR_CODES:
            raise StatisticsExportError(code)
        raise StatisticsExportError("operation_failed")
    except PermissionError:
        raise StatisticsExportError("permission_denied")
    except OSError:
        # File busy / locked / disk errors collapse to ``file_busy``.
        raise StatisticsExportError("file_busy")
    except Exception:
        raise StatisticsExportError("operation_failed")


def export_excel(start_date: str, end_date: str, path: str) -> str:
    return export_service.export_excel(start_date, end_date, path)


def export_all_local_data(path: str) -> str:
    return export_service.export_all_local_data(path)


__all__ = [
    "StatisticsExportError",
    "export_all_local_data",
    "export_excel",
    "export_statistics_csv",
]
