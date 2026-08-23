from __future__ import annotations

import pytest

from tests.support.activity_factory import create_closed_activity
from worktrace.constants import STATUS_EXCLUDED
from worktrace.domain_limits import RULE_PREVIEW_SCAN_LIMIT
from worktrace.services import (
    history_mutation_job_service,
    project_service,
    report_projection_snapshot_service,
    report_session_operation_service,
    rule_batch_service,
    rule_history_application_service,
    rule_impact_service,
    rule_service,
    statistics_service,
    statistics_snapshot_provider,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-08-17"


def test_timeline_mutation_reuses_preview_and_matches_canonical_snapshot(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Mutation perf")
    activity_id = create_closed_activity(
        day=DATE,
        start="09:00:00",
        end="09:30:00",
        window_title="Mutation.docx",
        project_id=project_id,
    )
    create_closed_activity(
        day=DATE,
        start="10:00:00",
        end="10:05:00",
        app_name="Private",
        process_name="private.exe",
        window_title="Excluded",
        status=STATUS_EXCLUDED,
    )
    before = report_projection_snapshot_service.build_visible_snapshot(DATE, DATE)
    source = next(
        session
        for session in before.final_sessions
        if activity_id in {int(value) for value in session.get("activity_ids") or []}
    )

    original_compute = report_projection_snapshot_service.compute_projection
    calls = 0

    def counted_compute(conn, start_date, end_date):
        nonlocal calls
        calls += 1
        return original_compute(conn, start_date, end_date)

    monkeypatch.setattr(
        report_projection_snapshot_service,
        "compute_projection",
        counted_compute,
    )
    result = report_session_operation_service.edit_session(
        DATE,
        str(source["projection_instance_key"]),
        str(source["projection_revision"]),
        "perf-contract-edit",
        project_id=None,
        duration_touched=False,
        adjusted_duration_seconds=None,
        note="updated note",
    )
    assert result.outcome_type == "operation_committed"
    assert calls == 1

    monkeypatch.setattr(
        report_projection_snapshot_service,
        "compute_projection",
        original_compute,
    )
    canonical = report_projection_snapshot_service.build_visible_snapshot(DATE, DATE)
    assert result.snapshot_revision == canonical.snapshot_revision
    selected = next(
        session
        for session in canonical.final_sessions
        if str(session.get("projection_instance_key") or "")
        == str(result.selection_hint["projection_instance_key"])
    )
    assert str(selected.get("projection_revision") or "") == str(
        result.selection_hint["projection_revision"]
    )


def test_statistics_realtime_cache_reuses_range_and_invalidates_on_generation(
    temp_db,
    monkeypatch,
):
    first_project = project_service.create_project("Stats cache A")
    second_project = project_service.create_project("Stats cache B")
    create_closed_activity(
        day=DATE,
        start="11:00:00",
        end="11:20:00",
        window_title="Stats.xlsx",
        project_id=first_project,
    )
    statistics_snapshot_provider.clear_statistics_snapshot_cache()

    original_compute = report_projection_snapshot_service.compute_projection
    calls = 0

    def counted_compute(conn, start_date, end_date):
        nonlocal calls
        calls += 1
        return original_compute(conn, start_date, end_date)

    monkeypatch.setattr(
        report_projection_snapshot_service,
        "compute_projection",
        counted_compute,
    )
    statistics_service.get_statistics_realtime_export_summary(
        DATE,
        DATE,
        first_project,
    )
    statistics_service.get_statistics_realtime_export_summary(
        DATE,
        DATE,
        second_project,
    )
    assert calls == 1

    project_service.create_project("Stats cache generation bump")
    statistics_service.get_statistics_realtime_export_summary(
        DATE,
        DATE,
        first_project,
    )
    assert calls == 2


def test_rule_previews_share_a_bounded_candidate_scan(temp_db, monkeypatch):
    project_id = project_service.create_project("Preview bounded")
    first_rule = rule_service.create_rule("bounded-first", project_id)
    second_rule = rule_service.create_rule("bounded-second", project_id)
    limits: list[int | None] = []

    def fake_load(_conn, *, after_id=0, cutoff_id=None, limit=None):
        del after_id, cutoff_id
        limits.append(limit)
        size = int(limit or 0)
        return [{"id": index + 1} for index in range(size)]

    def fake_classify(_conn, _activities, _rule, _rule_type):
        result = rule_impact_service.planner.zero_counts()
        result["would_update"] = []
        return result

    monkeypatch.setattr(
        rule_impact_service.planner,
        "load_candidate_activities",
        fake_load,
    )
    monkeypatch.setattr(
        rule_impact_service.planner,
        "classify_activities",
        fake_classify,
    )

    single = rule_impact_service.preview_rule_impact("keyword", first_rule)
    batch = rule_batch_service.preview_project_rules_batch_impact(
        [
            {"rule_type": "keyword", "rule_id": first_rule},
            {"rule_type": "keyword", "rule_id": second_rule},
        ]
    )

    assert limits == [RULE_PREVIEW_SCAN_LIMIT + 1, RULE_PREVIEW_SCAN_LIMIT + 1]
    assert single["truncated"] is True
    assert single["scan_complete"] is False
    assert single["scanned_activity_count"] == RULE_PREVIEW_SCAN_LIMIT
    assert batch["truncated"] is True
    assert batch["scan_complete"] is False
    assert batch["scanned_activity_count"] == RULE_PREVIEW_SCAN_LIMIT


def test_history_submission_keeps_bounded_synchronous_fast_path(
    temp_db,
    monkeypatch,
):
    single_seen: dict[str, object] = {}
    batch_seen: dict[str, object] = {}

    def fake_submit_rule_job(rule_type, rule_id, **kwargs):
        single_seen.update(
            {
                "rule_type": rule_type,
                "rule_id": rule_id,
                **kwargs,
            }
        )
        return {"queued": True, "status": "queued", "job_id": 1}

    def fake_submit_rule_batch_job(rules, **kwargs):
        batch_seen.update({"rules": rules, **kwargs})
        return {"queued": True, "status": "queued", "job_id": 2}

    monkeypatch.setattr(
        history_mutation_job_service,
        "submit_rule_job",
        fake_submit_rule_job,
    )
    monkeypatch.setattr(
        history_mutation_job_service,
        "submit_rule_batch_job",
        fake_submit_rule_batch_job,
    )

    rule_history_application_service.apply_rule_to_history("keyword", 1)
    rule_batch_service.backfill_project_rules_batch(
        [{"rule_type": "keyword", "rule_id": 1}]
    )

    assert single_seen["synchronous_scan_limit"] == 100
    assert batch_seen["synchronous_scan_limit"] == (
        rule_batch_service.MAX_BATCH_BACKFILL_ACTIVITIES + 1
    )
