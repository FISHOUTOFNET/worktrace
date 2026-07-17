from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.db import get_connection
from worktrace.services.activity_fact_repair_service import (
    repair_missing_activity_resources,
)
from worktrace.services.report_fact_query_service import load_report_activity_rows

pytestmark = [pytest.mark.db, pytest.mark.integration]

DATE = "2026-07-17"


def _closed_activity() -> int:
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Repair.docx - Word",
        file_path_hint="D:\\Repair\\Repair.docx",
        start_time=f"{DATE} 09:00:00",
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.close_activity(activity_id, f"{DATE} 09:10:00")
    return activity_id


def test_report_read_does_not_recreate_missing_resource_fact(temp_db):
    activity_id = _closed_activity()
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        )

    rows = load_report_activity_rows(DATE, DATE)

    row = next(item for item in rows if int(item["id"]) == activity_id)
    assert row["resource_kind"] == "unknown"
    assert row["resource_identity_key"] == f"activity:{activity_id}"
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()["c"]
    assert count == 0


def test_missing_resource_repair_is_persistent_and_idempotent(temp_db):
    activity_id = _closed_activity()
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        )

    assert repair_missing_activity_resources(batch_size=1) == 1
    assert repair_missing_activity_resources(batch_size=1) == 0

    with get_connection() as conn:
        resource = conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert resource is not None
    assert resource["identity_key"]
    rows = load_report_activity_rows(DATE, DATE)
    row = next(item for item in rows if int(item["id"]) == activity_id)
    assert row["resource_kind"] == resource["resource_kind"]
    assert row["resource_identity_key"] == resource["identity_key"]
