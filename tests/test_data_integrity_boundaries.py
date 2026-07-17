from __future__ import annotations

import sqlite3

import pytest

from tests.support import activity_factory as activity_service
from worktrace.constants import STATUS_ERROR
from worktrace.domain_limits import NOTE_MAX_LENGTH
from worktrace.services.secure_backup_validation import (
    BackupValidationError,
    _validate_operation_payload,
)


pytestmark = [pytest.mark.contract, pytest.mark.db]


def test_reverse_clock_close_marks_error_before_clamping(temp_db):
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc",
        start_time="2026-07-01 10:00:00",
    )

    activity_service.close_activity_row(
        activity_id,
        "2026-07-01 09:59:00",
    )

    row = activity_service.get_activity(activity_id)
    assert row["end_time"] == "2026-07-01 10:00:00"
    assert int(row["duration_seconds"]) == 0
    assert row["status"] == STATUS_ERROR


def test_backup_operation_rejects_note_above_domain_limit():
    operation = {
        "operation_type": "edit_session",
        "payload": {
            "payload_version": 4,
            "note": {"mode": "set", "value": "x" * (NOTE_MAX_LENGTH + 1)},
        },
    }
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(BackupValidationError, match="note value length"):
            _validate_operation_payload(operation, conn)
    finally:
        conn.close()
