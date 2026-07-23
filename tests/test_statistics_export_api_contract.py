"""Statistics export API contract tests.

Tests ``worktrace.api.export_api.export_statistics_csv`` facade/error mapping
without creating a real database, seeding activity, computing a real ticket,
or writing a real CSV file.

The service function ``export_service.write_statistics_csv`` is patched to
raise specific exceptions so the API's error mapping can be verified in
isolation. Uses a fixed non-empty ticket ``"ticket-for-api-contract"``
because API error mapping does not depend on ticket validity.
"""

from __future__ import annotations

import errno
from unittest.mock import patch

import pytest

from worktrace.api import export_api
from worktrace.api.export_api import StatisticsExportError
from worktrace.services import export_service

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

_TICKET = "ticket-for-api-contract"
_PATCH_TARGET = "worktrace.services.export_service.write_statistics_csv"

_SENSITIVE_TOKENS = (
    "traceback",
    "secret",
    "select",
    "c:\\",
    "a1.docx",
    "window_title",
    "file_path_hint",
    "note",
)


@pytest.mark.parametrize(
    "code",
    [
        "permission_denied",
        "file_busy",
        "storage_unavailable",
        "write_failed",
        "cleanup_failed",
        "invalid_path",
        "operation_failed",
    ],
)
def test_api_export_maps_export_file_error_to_stable_code(code):
    """ExportFileError codes in the known set are passed through verbatim."""
    with patch(_PATCH_TARGET, side_effect=export_service.ExportFileError(code)):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", "x.csv", _TICKET
            )
        assert exc.value.code == code


def test_api_export_maps_unknown_export_file_error_code():
    """ExportFileError with an unknown code collapses to operation_failed."""
    with patch(
        _PATCH_TARGET, side_effect=export_service.ExportFileError("unknown_code")
    ):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", "x.csv", _TICKET
            )
        assert exc.value.code == "operation_failed"


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (PermissionError("denied"), "permission_denied"),
        (OSError(errno.EBUSY, "busy"), "file_busy"),
    ],
)
def test_api_export_maps_oserror_to_classified_code(exception, code):
    """OSError is classified and mapped to a stable code."""
    with patch(_PATCH_TARGET, side_effect=exception):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", "x.csv", _TICKET
            )
        assert exc.value.code == code


@pytest.mark.parametrize(
    "code",
    [
        "invalid_date",
        "invalid_range",
        "range_too_large",
        "empty_data",
        "invalid_path",
        "stale_statistics_snapshot",
    ],
)
def test_api_export_maps_known_value_error(code):
    """Known ValueError codes are mapped to StatisticsExportError with the same code."""
    with patch(_PATCH_TARGET, side_effect=ValueError(code)):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", "x.csv", _TICKET
            )
        assert exc.value.code == code


def test_api_export_maps_unknown_value_error():
    """Unknown ValueError messages are mapped to operation_failed."""
    with patch(_PATCH_TARGET, side_effect=ValueError("something_unexpected")):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", "x.csv", _TICKET
            )
        assert exc.value.code == "operation_failed"


def test_api_export_maps_unknown_exception():
    """Unknown exception types are mapped to operation_failed."""
    with patch(_PATCH_TARGET, side_effect=RuntimeError("unexpected")):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", "x.csv", _TICKET
            )
        assert exc.value.code == "operation_failed"


def test_api_export_reraises_statistics_export_error():
    """StatisticsExportError from the service is re-raised without wrapping."""
    original_error = StatisticsExportError("permission_denied")
    with patch(_PATCH_TARGET, side_effect=original_error):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", "x.csv", _TICKET
            )
        assert exc.value is original_error


def test_api_export_error_never_leaks_internals():
    """Error messages must not leak paths, SQL, tracebacks, or sensitive fields."""
    sensitive = "Traceback SELECT FROM C:\\secret\\A1.docx"
    with patch(_PATCH_TARGET, side_effect=PermissionError(sensitive)):
        with pytest.raises(StatisticsExportError) as exc:
            export_api.export_statistics_csv(
                "2026-06-25", "2026-06-25", "x.csv", _TICKET
            )
    lowered = str(exc.value).lower()
    for token in _SENSITIVE_TOKENS:
        assert token not in lowered


def test_api_export_passes_parameters_through(tmp_path):
    """Parameters are passed verbatim to the service."""
    out = tmp_path / "report.csv"
    return_value = {
        "activity_count": 1,
        "duration_seconds": 1800,
        "filename": "report.csv",
    }
    with patch(_PATCH_TARGET, return_value=return_value) as mock:
        result = export_api.export_statistics_csv(
            "2026-06-25", "2026-06-27", out, _TICKET, "42"
        )
    mock.assert_called_once_with("2026-06-25", "2026-06-27", out, _TICKET, "42")
    assert result["filename"] == "report.csv"
    assert result["activity_count"] == 1


def test_api_export_passes_none_project_id(tmp_path):
    """When project_id is None, it is passed through as None."""
    out = tmp_path / "report.csv"
    return_value = {
        "activity_count": 1,
        "duration_seconds": 1800,
        "filename": "report.csv",
    }
    with patch(_PATCH_TARGET, return_value=return_value) as mock:
        export_api.export_statistics_csv(
            "2026-06-25", "2026-06-25", out, _TICKET
        )
    mock.assert_called_once_with("2026-06-25", "2026-06-25", out, _TICKET, None)
