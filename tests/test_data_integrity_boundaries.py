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
            "payload_version": 6,
            "replay_binding": "members",
            "note": {"mode": "set", "value": "x" * (NOTE_MAX_LENGTH + 1)},
        },
    }
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(BackupValidationError, match="note value length"):
            _validate_operation_payload(operation, conn)
    finally:
        conn.close()


def _make_valid_backup_operation() -> dict:
    """Return a minimal payload that passes the backup validator's contract."""

    return {
        "operation_type": "hide_session",
        "payload": {
            "payload_version": 6,
            "replay_binding": "members",
        },
    }


def test_backup_validator_rejects_legacy_payload_version():
    operation = _make_valid_backup_operation()
    operation["payload"]["payload_version"] = 4
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(BackupValidationError, match="operation payload version"):
            _validate_operation_payload(operation, conn)
    finally:
        conn.close()


def test_backup_validator_rejects_legacy_revision_binding():
    operation = _make_valid_backup_operation()
    operation["payload"]["replay_binding"] = "revision"
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(BackupValidationError, match="operation replay binding"):
            _validate_operation_payload(operation, conn)
    finally:
        conn.close()


def test_backup_validator_rejects_non_members_binding():
    operation = _make_valid_backup_operation()
    operation["payload"]["replay_binding"] = "something_else"
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(BackupValidationError, match="operation replay binding"):
            _validate_operation_payload(operation, conn)
    finally:
        conn.close()


def test_backup_validator_rejects_missing_binding():
    operation = _make_valid_backup_operation()
    del operation["payload"]["replay_binding"]
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(BackupValidationError, match="operation replay binding"):
            _validate_operation_payload(operation, conn)
    finally:
        conn.close()


def test_backup_validator_rejects_unknown_payload_field():
    operation = _make_valid_backup_operation()
    operation["payload"]["rogue_field"] = 1
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(BackupValidationError, match="unknown payload field"):
            _validate_operation_payload(operation, conn)
    finally:
        conn.close()


def test_backup_validator_rejects_unknown_operation_type():
    operation = _make_valid_backup_operation()
    operation["operation_type"] = "unknown_op"
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(BackupValidationError, match="operation type"):
            _validate_operation_payload(operation, conn)
    finally:
        conn.close()


def test_backup_validator_accepts_members_only_current_payload():
    operation = _make_valid_backup_operation()
    conn = sqlite3.connect(":memory:")
    try:
        _validate_operation_payload(operation, conn)
    finally:
        conn.close()
