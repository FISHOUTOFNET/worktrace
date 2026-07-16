from __future__ import annotations

import json

import pytest

from tests.support import activity_factory as activity_service
from worktrace.db import get_connection
from worktrace.services import project_service
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


def test_minute_editor_baseline_does_not_create_duration_override_on_note_only_save(temp_db):
    project_id = project_service.create_project("P")
    _closed("10:00:00", "10:10:25", project_id=project_id)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert source["duration_seconds"] == 625
    assert source["has_duration_override"] is False

    result = mutations.edit_session(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "note-with-rounded-duration",
        project_id=None,
        adjusted_duration_seconds=600,
        note="memo",
    )
    assert result.outcome_type == "operation_committed"
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert updated["duration_seconds"] == 625
    assert updated["has_duration_override"] is False
    assert updated["session_note"] == "memo"

    with get_connection() as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM report_session_operation WHERE id = ?",
                (result.operation_id,),
            ).fetchone()[0]
        )
    assert "duration" not in payload


def test_existing_exact_duration_override_is_preserved_by_unchanged_rounded_editor_value(temp_db):
    project_id = project_service.create_project("P")
    _closed("11:00:00", "11:10:25", project_id=project_id)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    first = mutations.edit_session(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "set-exact-duration",
        project_id=None,
        adjusted_duration_seconds=610,
        note="",
    )
    assert first.outcome_type == "operation_committed"
    overridden = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert overridden["has_duration_override"] is True
    assert overridden["adjusted_duration_seconds"] == 610

    second = mutations.edit_session(
        DATE,
        overridden["projection_instance_key"],
        overridden["projection_revision"],
        "note-preserves-exact-duration",
        project_id=None,
        adjusted_duration_seconds=600,
        note="memo",
    )
    assert second.outcome_type == "operation_committed"
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert updated["duration_seconds"] == 610
    assert updated["adjusted_duration_seconds"] == 610
    assert updated["has_duration_override"] is True
    assert updated["session_note"] == "memo"


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


def test_attributed_excluded_is_redacted_without_reclassifying_the_whole_project_session(temp_db):
    project_id = project_service.create_project("P")
    _closed("09:00:00", "09:10:00", project_id=project_id, app="NormalA")
    excluded_id = _closed("09:10:00", "09:12:00", status="excluded", app="Secret")
    _closed("09:12:00", "09:20:00", project_id=project_id, app="NormalB")

    snapshot = build_visible_snapshot(DATE, DATE)
    assert len(snapshot.final_sessions) == 1
    assert snapshot.standalone_status_entries == ()
    session = snapshot.final_sessions[0]
    assert session["project_name"] == "P"
    assert session["duration_seconds"] == 20 * 60

    excluded_rows = [
        row
        for row in snapshot.final_contributions
        if int(row.get("activity_id") or 0) == excluded_id
    ]
    assert len(excluded_rows) == 1
    excluded = excluded_rows[0]
    assert excluded["privacy_redacted"] is True
    assert excluded["activity_display_name"] == "已排除"
    assert excluded["app_name"] == ""
    assert excluded["process_name"] == ""
    assert excluded["resource_identity_key"] == ""
    assert "Secret" not in json.dumps(excluded, ensure_ascii=False)

    details = get_projection_session_activity_summary(
        session["projection_instance_key"],
        DATE,
        expected_projection_revision=session["projection_revision"],
    )
    assert "Secret" not in json.dumps(details, ensure_ascii=False)
    assert any(row["activity_name"] == "已排除" for row in details["summary_rows"])

    analytics = build_statistics_projection(snapshot)
    assert analytics.total_duration_seconds == 20 * 60
    assert analytics.project_duration_seconds == 20 * 60
    assert analytics.classified_duration_seconds == 20 * 60
    assert analytics.excluded_duration_seconds == 2 * 60
    assert analytics.uncategorized_duration_seconds == 0
    assert analytics.by_project[0]["display_name"] == "P"
    assert analytics.by_project[0]["duration_seconds"] == 20 * 60
    by_status = {row["key"]: row["duration_seconds"] for row in analytics.by_status}
    assert by_status["excluded"] == 2 * 60
    assert analytics.export_records[0]["project"] == "P"
    assert "已排除" in analytics.export_records[0]["status"]
    assert "Secret" not in json.dumps(analytics.export_records, ensure_ascii=False)


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
