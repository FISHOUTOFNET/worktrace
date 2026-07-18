from __future__ import annotations

import json

import pytest

from tests.support import activity_factory
from worktrace.db import get_connection
from worktrace.services import (
    activity_inference_job_repository as jobs,
    secure_backup_service,
)

pytestmark = [pytest.mark.db, pytest.mark.contract]


def test_payload_v5_preserves_exact_inference_job(temp_db):
    activity_id = activity_factory.create_activity(
        "Word",
        "winword.exe",
        "Contract",
        start_time="2026-07-18 10:00:00",
    )
    activity_factory.close_activity_row(
        activity_id,
        "2026-07-18 10:05:00",
    )
    with get_connection() as conn:
        jobs.enqueue_closed_activity_ids(
            conn,
            [activity_id],
            reason=jobs.REASON_FACTS_CHANGED,
            at_time="2026-07-18 10:06:00",
        )
        jobs.record_failure(
            conn,
            activity_id,
            jobs.InferenceJobErrorCode.DATA_REPAIR_REQUIRED,
            at_time="2026-07-18 10:07:00",
        )
        expected = dict(
            conn.execute(
                "SELECT * FROM activity_inference_job WHERE activity_id = ?",
                (activity_id,),
            ).fetchone()
        )

    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )

    assert payload["version"] == 5
    assert payload["schema_version"] == "11"
    assert payload["tables"]["activity_inference_job"] == [expected]
    assert "activity_inference_job" not in secure_backup_service.EXPORT_TABLES_V4


def test_payload_v5_rejects_unbounded_job_error_text(temp_db):
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["activity_inference_job"] = [
        {
            "activity_id": 1,
            "reason": jobs.REASON_FINALIZE,
            "attempt_count": 1,
            "available_at": "2026-07-18 10:00:00",
            "last_error_code": "C:/secret/client.txt",
            "created_at": "2026-07-18 10:00:00",
            "updated_at": "2026-07-18 10:00:00",
        }
    ]

    with pytest.raises(
        secure_backup_service.BackupCorruptedError,
        match="invalid or corrupted",
    ):
        secure_backup_service._parse_and_validate_payload(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
