"""Excel and local-data export facade for the UI.

The facade maps service-layer validation and infrastructure failures to stable,
path-free codes. Raw platform error text never crosses the API boundary.
"""
from __future__ import annotations

from typing import Any

from ..services import export_service
from .statistics_interactive_range_policy import validate_interactive_statistics_range


class StatisticsExportError(ValueError):
    """Raised by the statistics CSV export for known user-facing failures."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_EXPORT_VALUE_ERROR_CODES = {
    "invalid_date",
    "invalid_range",
    "range_too_large",
    "invalid_project",
    "empty_data",
    "invalid_path",
    "stale_statistics_snapshot",
}
_EXPORT_FILE_ERROR_CODES = {
    "permission_denied",
    "file_busy",
    "storage_unavailable",
    "write_failed",
    "cleanup_failed",
    "invalid_path",
    "operation_failed",
}


def _map_statistics_export_failure(action):
    try:
        return action()
    except StatisticsExportError:
        raise
    except export_service.ExportFileError as exc:
        code = exc.code if exc.code in _EXPORT_FILE_ERROR_CODES else "operation_failed"
        raise StatisticsExportError(code) from exc
    except OSError as exc:
        code = export_service.classify_export_os_error(exc)
        if code not in _EXPORT_FILE_ERROR_CODES:
            code = "operation_failed"
        raise StatisticsExportError(code) from exc
    except ValueError as exc:
        code = str(exc)
        if code in _EXPORT_VALUE_ERROR_CODES:
            raise StatisticsExportError(code) from exc
        raise StatisticsExportError("operation_failed") from exc
    except Exception as exc:
        raise StatisticsExportError("operation_failed") from exc


def _prepare_interactive_statistics_csv(
    date_from: str,
    date_to: str,
    project_id: str | int | None,
):
    validate_interactive_statistics_range(date_from, date_to)
    return export_service.prepare_statistics_csv(date_from, date_to, project_id)


def _write_interactive_statistics_csv(
    date_from: str,
    date_to: str,
    output_path,
    expected_export_ticket_revision: str,
    project_id: str | int | None,
) -> dict[str, Any]:
    validate_interactive_statistics_range(date_from, date_to)
    return export_service.write_statistics_csv(
        date_from,
        date_to,
        output_path,
        expected_export_ticket_revision,
        project_id,
    )


def prepare_statistics_csv(
    date_from: str,
    date_to: str,
    project_id: str | int | None = None,
):
    """Freeze a bounded point-in-time statistics export before path selection."""

    return _map_statistics_export_failure(
        lambda: _prepare_interactive_statistics_csv(
            date_from, date_to, project_id
        )
    )


def write_prepared_statistics_csv(prepared, output_path) -> dict[str, Any]:
    """Write a previously frozen statistics export without rereading live state."""

    return _map_statistics_export_failure(
        lambda: export_service.write_prepared_statistics_csv(prepared, output_path)
    )


def export_statistics_csv(
    date_from: str,
    date_to: str,
    output_path,
    expected_export_ticket_revision: str,
    project_id: str | int | None = None,
) -> dict[str, Any]:
    """Legacy ticket-bound CSV API retained for bounded compatibility callers."""

    return _map_statistics_export_failure(
        lambda: _write_interactive_statistics_csv(
            date_from,
            date_to,
            output_path,
            expected_export_ticket_revision,
            project_id,
        )
    )


def export_excel(start_date: str, end_date: str, path: str) -> str:
    return export_service.export_excel(start_date, end_date, path)


def export_all_local_data(path: str) -> str:
    return export_service.export_all_local_data(path)


__all__ = [
    "StatisticsExportError",
    "export_all_local_data",
    "export_excel",
    "export_statistics_csv",
    "prepare_statistics_csv",
    "write_prepared_statistics_csv",
]
