from __future__ import annotations

import json

import pytest

from worktrace.db import get_connection
from worktrace.services import activity_service, project_service
from worktrace.services import report_session_operation_service as mutations
from worktrace.services.export_service import build_statistics_csv_rows
from worktrace.services.project_activity_summary_service import get_projection_session_activity_summary
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.report_session_projection_service import public_session_dto
from worktrace.services.statistics_projection import build_statistics_projection

DATE = "2026-07-01"

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _closed(start: str, end: str, *, project_id: int | None = None, status: str = "normal", app: str = "App") -> int:
    activity_id = activity_service.create_activity(
        app, app.lower() + ".exe", app,
        project_id=project_id, status=status, start_time=f"{DATE} {start}",
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.close_activity(activity_id, f"{DATE} {end}")
    return activity_id


def test_all_canonical_read_surfaces_are_zero_write_and_connection_independent(temp_db):
    project_id = project_service.create_project("P")
    _closed("09:00:00", "09:10:00", project_id=project_id)
    before = temp_db.read_bytes()
    with get_connection() as conn:
        changes = conn.total_changes
        caller = build_visible_snapshot(DATE, DATE, conn=conn)
        assert conn.total_changes == changes
    owned = build_visible_snapshot(DATE, DATE)
    analytics = build_statistics_projection(owned)
    build_statistics_csv_rows(DATE, DATE)
    assert caller.snapshot_revision == owned.snapshot_revision == analytics.snapshot_revision
    assert temp_db.read_bytes() == before


def test_uow_returns_authoritative_post_state_and_exact_idempotent_receipt(temp_db):
    project_id = project_service.create_project("P")
    _closed("09:00:00", "09:10:00", project_id=project_id)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    result = mutations.copy_session(
        DATE, source["projection_instance_key"], source["projection_revision"], "copy-request",
    )
    assert result.snapshot_revision != ""
    assert result.selection_hint["projection_instance_key"] == f"copy:{result.operation_id}"
    assert result.selection_hint["projection_revision"]
    repeated = mutations.copy_session(
        DATE, source["projection_instance_key"], source["projection_revision"], "copy-request",
    )
    assert repeated.to_dict() == result.to_dict()
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM report_session_operation").fetchone()[0] == 1


def test_edit_no_effect_writes_only_receipt(temp_db):
    project_id = project_service.create_project("P")
    _closed("09:00:00", "09:10:00", project_id=project_id)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    result = mutations.edit_session(
        DATE, source["projection_instance_key"], source["projection_revision"], "noop",
        project_id=None, adjusted_duration_seconds=None, note="",
    )
    assert result.outcome_type == "no_op"
    assert result.operation_id is None
    assert result.selection_hint["projection_revision"] == source["projection_revision"]
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM report_session_operation").fetchone()[0] == 0
        assert conn.execute("SELECT outcome_type FROM report_mutation_request").fetchone()[0] == "no_op"


def test_standalone_excluded_is_timeline_entry_but_open_entry_is_not_exported(temp_db):
    _closed("09:00:00", "09:10:00", status="excluded", app="Secret")
    snapshot = build_visible_snapshot(DATE, DATE)
    assert len(snapshot.standalone_status_entries) == 1
    assert snapshot.final_entries[0]["row_kind"] == "standalone_status"
    records = build_statistics_projection(snapshot).export_records
    assert len(records) == 1
    assert records[0]["project"] == "已排除"
    assert "Secret" not in json.dumps(records, ensure_ascii=False)

    activity_service.create_activity("Secret", "secret.exe", "Secret", status="excluded", start_time=f"{DATE} 10:00:00")
    snapshot = build_visible_snapshot(DATE, DATE)
    assert len(snapshot.standalone_status_entries) == 2
    assert len(build_statistics_projection(snapshot).export_records) == 1


def test_details_resolves_actual_revision_and_public_dto_is_allowlisted(temp_db):
    project_id = project_service.create_project("P")
    _closed("09:00:00", "09:10:00", project_id=project_id)
    session = build_visible_snapshot(DATE, DATE).final_sessions[0]
    details = get_projection_session_activity_summary(
        session["projection_instance_key"], DATE,
        expected_projection_revision=session["projection_revision"],
    )
    assert details["resolved_projection_revision"] == session["projection_revision"]
    dto = public_session_dto(session)
    assert not any(key.startswith("_") for key in dto)
    assert "payload_json" not in dto
    with pytest.raises(ValueError, match="stale_selection"):
        get_projection_session_activity_summary(
            session["projection_instance_key"], DATE,
            expected_projection_revision="0" * 40,
        )
