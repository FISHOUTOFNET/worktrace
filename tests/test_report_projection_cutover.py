from __future__ import annotations

import json

import pytest

from tests.support import activity_factory as activity_service
from worktrace.db import get_connection, now_str
from worktrace.domain_limits import (
    NOTE_MAX_LENGTH,
    TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH,
)
from worktrace.services import project_service
from worktrace.services import report_session_operation_service as mutations
from worktrace.services.export_service import build_statistics_csv_rows
from worktrace.services.project_activity_summary_service import get_projection_session_activity_summary
from worktrace.services.report_projection_identity import member_identity_key
from worktrace.services.report_projection_model import InvalidInputError
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.report_session_projection_service import public_session_dto
from worktrace.services.report_session_operation_engine import OPERATION_PAYLOAD_VERSION
from worktrace.services.statistics_projection import build_statistics_projection
from worktrace.integrations.fd_work.contracts import FDWorkEntryRequest
from worktrace.integrations.fd_work.entry_service import FDWorkEntryService

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
        project_id=None, duration_touched=False, adjusted_duration_seconds=None, note="",
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
        duration_touched=False,
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


def test_explicit_duration_intent_sets_normalized_override_across_report_consumers(temp_db):
    project_id = project_service.create_project("MATTER-4442")
    _closed("15:00:00", "16:14:02", project_id=project_id, app="Observed")
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert source["duration_seconds"] == 4_442
    assert source["has_duration_override"] is False

    result = mutations.edit_session(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "explicit-normalized-duration",
        project_id=None,
        duration_touched=True,
        adjusted_duration_seconds=4_320,
        note="Synthetic FD narrative",
    )
    assert result.outcome_type == "operation_committed"

    snapshot = build_visible_snapshot(DATE, DATE)
    session = snapshot.final_sessions[0]
    assert session["adjusted_duration_seconds"] == 4_320
    assert session["has_duration_override"] is True
    assert session["duration_seconds"] == 4_320

    with get_connection() as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM report_session_operation WHERE id = ?",
                (result.operation_id,),
            ).fetchone()[0]
        )
    assert payload["duration"] == {"mode": "set", "value": 4_320}

    details = get_projection_session_activity_summary(
        session["projection_instance_key"],
        DATE,
        expected_projection_revision=session["projection_revision"],
    )
    assert sum(row["duration_seconds"] for row in details["summary_rows"]) == 4_442
    assert build_statistics_projection(snapshot).total_duration_seconds == 4_320
    assert build_statistics_csv_rows(DATE, DATE)[0]["duration_seconds"] == 4_320
    draft = FDWorkEntryService(enabled_reader=lambda: True).build_draft(
        FDWorkEntryRequest(
            report_date=DATE,
            projection_instance_key=session["projection_instance_key"],
            expected_projection_revision=session["projection_revision"],
        )
    )
    assert draft.duration_hours == "1.2"


def test_existing_normalized_duration_override_is_preserved_by_equivalent_input(temp_db):
    project_id = project_service.create_project("P")
    _closed("11:00:00", "11:10:25", project_id=project_id)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    first = mutations.edit_session(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "set-exact-duration",
        project_id=None,
        duration_touched=True,
        adjusted_duration_seconds=1_080,
        note="",
    )
    assert first.outcome_type == "operation_committed"
    overridden = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert overridden["has_duration_override"] is True
    assert overridden["adjusted_duration_seconds"] == 1_080

    second = mutations.edit_session(
        DATE,
        overridden["projection_instance_key"],
        overridden["projection_revision"],
        "note-preserves-exact-duration",
        project_id=None,
        duration_touched=False,
        adjusted_duration_seconds=1_070,
        note="memo",
    )
    assert second.outcome_type == "operation_committed"
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert updated["duration_seconds"] == 1_080
    assert updated["adjusted_duration_seconds"] == 1_080
    assert updated["has_duration_override"] is True
    assert updated["session_note"] == "memo"


def test_new_timeline_description_edit_over_200_is_rejected(temp_db):
    project_id = project_service.create_project("P")
    _closed("12:00:00", "12:10:00", project_id=project_id)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]

    with pytest.raises(InvalidInputError):
        mutations.edit_session(
            DATE,
            source["projection_instance_key"],
            source["projection_revision"],
            "description-over-200",
            project_id=None,
            duration_touched=False,
            adjusted_duration_seconds=None,
            note="新" * (TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH + 1),
        )

    with get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM report_session_operation"
        ).fetchone()[0] == 0


def test_unchanged_historical_long_description_allows_project_and_duration_edit(temp_db):
    first_project = project_service.create_project("Historical A")
    second_project = project_service.create_project("Historical B")
    _closed("13:00:00", "13:10:00", project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    historical_note = "旧" * 300
    assert TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH < len(historical_note) <= NOTE_MAX_LENGTH

    with get_connection() as conn:
        operation_id = 1
        conn.execute(
            """
            INSERT INTO report_session_operation(
                id, report_date, sequence, operation_type, source_instance_key,
                source_expected_revision, target_instance_key,
                target_expected_revision, direction, undo_of_operation_id,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (
                operation_id,
                DATE,
                1,
                "edit_session",
                source["projection_instance_key"],
                source["projection_revision"],
                json.dumps(
                    {
                        "payload_version": OPERATION_PAYLOAD_VERSION,
                        "replay_binding": "members",
                        "note": {"mode": "set", "value": historical_note},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now_str(),
            ),
        )
        for order, member_slice in enumerate(source["member_slices"]):
            report_date, activity_id, slice_start = member_identity_key(member_slice)
            conn.execute(
                """
                INSERT INTO report_session_operation_member(
                    operation_id, role, activity_id, report_date,
                    slice_start_time, display_order
                ) VALUES (?, 'source', ?, ?, ?, ?)
                """,
                (operation_id, activity_id, report_date, slice_start, order),
            )
        conn.commit()

    historical = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert historical["session_note"] == historical_note

    result = mutations.edit_session(
        DATE,
        historical["projection_instance_key"],
        historical["projection_revision"],
        "historical-long-project-duration",
        project_id=second_project,
        duration_touched=True,
        adjusted_duration_seconds=1_080,
        note=historical_note,
    )

    assert result.outcome_type == "operation_committed"
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert int(updated["project_id"]) == second_project
    assert updated["adjusted_duration_seconds"] == 1_080
    assert updated["session_note"] == historical_note


def test_durable_note_limit_remains_2000():
    assert NOTE_MAX_LENGTH == 2000
    assert TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH == 200


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


def test_observed_activity_details_stay_raw_while_report_consumers_use_override(temp_db):
    project_id = project_service.create_project("Observed versus reported")
    _closed("14:00:00", "14:00:30", project_id=project_id, app="First")
    _closed("14:00:30", "14:01:40", project_id=project_id, app="Second")
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert source["duration_seconds"] == 100

    mutations.edit_session(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "observed-reported-override",
        project_id=None,
        duration_touched=True,
        adjusted_duration_seconds=720,
        note="FD narrative",
    )
    snapshot = build_visible_snapshot(DATE, DATE)
    session = snapshot.final_sessions[0]
    contributions = list(snapshot.final_contributions)

    assert session["duration_seconds"] == 720
    assert [row["observed_duration_seconds"] for row in contributions] == [30, 70]
    assert [row["report_duration_seconds"] for row in contributions] == [216, 504]
    assert sum(row["duration_seconds"] for row in contributions) == 720

    details = get_projection_session_activity_summary(
        session["projection_instance_key"],
        DATE,
        expected_projection_revision=session["projection_revision"],
    )
    assert sorted(row["duration_seconds"] for row in details["summary_rows"]) == [30, 70]
    assert sum(row["duration_seconds"] for row in details["summary_rows"]) == 100

    analytics = build_statistics_projection(snapshot)
    assert analytics.total_duration_seconds == 720
    assert build_statistics_csv_rows(DATE, DATE)[0]["duration_seconds"] == 720
    draft = FDWorkEntryService(enabled_reader=lambda: True).build_draft(
        FDWorkEntryRequest(
            report_date=DATE,
            projection_instance_key=session["projection_instance_key"],
            expected_projection_revision=session["projection_revision"],
        )
    )
    assert draft.duration_hours == "0.2"
