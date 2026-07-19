from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.db import get_connection
from worktrace.resources.types import DetectedResource
from worktrace.services import activity_fact_repair_service as repair_service
from worktrace.services.report_fact_query_service import load_report_activity_rows

pytestmark = [pytest.mark.db, pytest.mark.integration]

DATE = "2026-07-17"


def _closed_activity(*, minute: int = 0) -> int:
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Repair.docx - Word",
        file_path_hint="D:\\Repair\\Repair.docx",
        start_time=f"{DATE} 09:{minute:02d}:00",
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.close_activity(activity_id, f"{DATE} 09:{minute + 1:02d}:00")
    return activity_id


def _delete_resource(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        )


def _resource(identity_key: str, display_name: str) -> DetectedResource:
    return DetectedResource(
        resource_kind="local_file",
        resource_subtype="document",
        display_name=display_name,
        identity_key=identity_key,
        is_anchor=True,
        confidence=100,
        source="repair_test",
        app_name="Word",
        process_name="winword.exe",
        window_title="Repair.docx - Word",
        path_hint="D:\\Repair\\Repair.docx",
    )


def test_report_read_fails_closed_without_recreating_missing_fact(temp_db):
    activity_id = _closed_activity()
    _delete_resource(activity_id)

    with pytest.raises(ValueError, match="data_repair_required"):
        load_report_activity_rows(DATE, DATE)

    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()["c"]
    assert count == 0


def test_missing_resource_repair_is_persistent_versioned_and_idempotent(temp_db):
    activity_id = _closed_activity()
    _delete_resource(activity_id)

    assert repair_service.repair_missing_activity_resources(batch_size=1) == 1
    assert repair_service.repair_missing_activity_resources(batch_size=1) == 0

    state = repair_service.require_activity_fact_repair_complete()
    assert state["policy_version"] == repair_service.REPAIR_POLICY_VERSION
    assert state["status"] == "completed"
    assert state["repaired_count"] == 1
    assert state["cursor_activity_id"] == activity_id
    assert state["completed_at"]

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


def test_resource_repair_executes_one_bounded_batch_per_call(temp_db):
    activity_ids = [_closed_activity(minute=index * 2) for index in range(3)]
    for activity_id in activity_ids:
        _delete_resource(activity_id)

    assert repair_service.repair_missing_activity_resources(batch_size=1) == 1
    first_state = repair_service.get_activity_fact_repair_state()
    assert first_state["status"] == "running"
    assert first_state["processed_count"] == 1
    assert first_state["cursor_activity_id"] == activity_ids[0]

    with get_connection() as conn:
        repaired_ids = [
            int(row["activity_id"])
            for row in conn.execute(
                "SELECT activity_id FROM activity_resource ORDER BY activity_id"
            ).fetchall()
        ]
    assert repaired_ids == [activity_ids[0]]

    assert repair_service.repair_missing_activity_resources(batch_size=1) == 1
    assert repair_service.repair_missing_activity_resources(batch_size=1) == 1
    state = repair_service.require_activity_fact_repair_complete()
    assert state["status"] == "completed"
    assert state["processed_count"] == 3
    assert state["repaired_count"] == 3


def test_detector_failure_persists_explicit_unknown_fact(temp_db, monkeypatch):
    activity_id = _closed_activity()
    _delete_resource(activity_id)

    def fail_detection(_window):
        raise RuntimeError("detector unavailable")

    monkeypatch.setattr(repair_service, "detect_resource", fail_detection)

    assert repair_service.repair_missing_activity_resources(batch_size=1) == 1

    state = repair_service.require_activity_fact_repair_complete()
    assert state["unknown_count"] == 1
    assert state["failed_count"] == 1
    with get_connection() as conn:
        resource = conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert resource["resource_kind"] == "unknown"
    assert resource["identity_key"] == f"activity:{activity_id}"
    assert resource["source"] == f"repair_v{repair_service.REPAIR_POLICY_VERSION}_unknown"


def test_empty_detector_identity_is_persisted_as_unknown(temp_db, monkeypatch):
    activity_id = _closed_activity()
    _delete_resource(activity_id)

    monkeypatch.setattr(
        repair_service,
        "detect_resource",
        lambda _window: _resource("", "Broken identity"),
    )

    assert repair_service.repair_missing_activity_resources(batch_size=1) == 1

    state = repair_service.require_activity_fact_repair_complete()
    assert state["unknown_count"] == 1
    assert state["failed_count"] == 1
    with get_connection() as conn:
        resource = conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert resource["resource_kind"] == "unknown"
    assert resource["identity_key"] == f"activity:{activity_id}"


def test_detector_changes_do_not_change_repaired_history(temp_db, monkeypatch):
    activity_id = _closed_activity()
    _delete_resource(activity_id)

    monkeypatch.setattr(
        repair_service,
        "detect_resource",
        lambda _window: _resource("repair:v1", "Repair V1"),
    )
    assert repair_service.repair_missing_activity_resources(batch_size=1) == 1
    first = next(
        row
        for row in load_report_activity_rows(DATE, DATE)
        if int(row["id"]) == activity_id
    )

    monkeypatch.setattr(
        repair_service,
        "detect_resource",
        lambda _window: _resource("repair:v2", "Repair V2"),
    )
    assert repair_service.repair_missing_activity_resources(batch_size=1) == 0
    second = next(
        row
        for row in load_report_activity_rows(DATE, DATE)
        if int(row["id"]) == activity_id
    )

    assert first["resource_identity_key"] == "repair:v1"
    assert second["resource_identity_key"] == "repair:v1"
    assert second["resource_display_name"] == "Repair V1"
