from __future__ import annotations

import logging

import pytest

from worktrace.collector import collector_health
from worktrace.collector.collector_failure_policy import CollectorFailureCode

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.unit]


def test_fatal_failure_logs_sanitized_exception_location_without_message(
    temp_db,
    caplog,
):
    caplog.set_level(logging.ERROR)

    try:
        raise RuntimeError("sensitive-local-value-must-not-be-logged")
    except RuntimeError:
        collector_health.record_fatal_failure(
            "active_window",
            CollectorFailureCode.UNEXPECTED_FAILURE,
            "2026-08-11 14:47:55",
        )

    assert "collector fatal failure phase=active_window code=unexpected_failure" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
    assert "test_fatal_failure_logs_sanitized_exception_location_without_message" in caplog.text
    assert "sensitive-local-value-must-not-be-logged" not in caplog.text
