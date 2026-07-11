from __future__ import annotations

from pathlib import Path

from tests.support.activity_factory import create_closed_activity
from tests.support.db_helpers import fetch_all
from tests.support.project_factory import create_folder_rule, create_keyword_rule, create_project

from worktrace.api import timeline_api
from worktrace.db import get_connection
from worktrace.services import (
    export_service,
    rule_batch_service,
    rule_impact_service,
    statistics_service,
    timeline_service,
    view_model_service,
)
from worktrace.services.project_inference_service import assign_project_for_activity


RAW_COLUMNS = (
    "id",
    "start_time",
    "end_time",
    "duration_seconds",
    "app_name",
    "process_name",
    "window_title",
    "file_path_hint",
    "status",
    "source",
    "created_at",
    "updated_at",
)


def _raw_snapshot() -> list[dict]:
    cols = ", ".join(RAW_COLUMNS)
    return fetch_all(f"SELECT {cols} FROM activity_log ORDER BY id")


def _session(day: str = "2026-06-25") -> dict:
    sessions = timeline_service.get_project_sessions_by_date(day, ensure_context=False)
    assert sessions
    return sessions[0]


def test_raw_activity_facts_immutable_across_rules_overrides_stats_and_export(temp_db):
    project = create_project("Contract Project")
    folder_project = create_project("Folder Project")
    keyword_project = create_project("Keyword Project")
    a1 = create_closed_activity(
        window_title="alpha contract",
        start="09:00:00",
        end="09:30:00",
        file_path_hint=r"D:\Contract\alpha.docx",
    )
    a2 = create_closed_activity(
        window_title="beta plain",
        start="09:30:00",
        end="10:00:00",
        file_path_hint=r"D:\Other\beta.docx",
    )
    before = _raw_snapshot()

    keyword_rule = create_keyword_rule(keyword_project, "alpha")
    folder_rule = create_folder_rule(folder_project, r"D:\Contract")
    rule_impact_service.backfill_rule_impact("keyword", keyword_rule)
    rule_impact_service.backfill_rule_impact("folder", folder_rule)
    rule_batch_service.backfill_project_rules_batch(
        [
            {"rule_type": "keyword", "rule_id": keyword_rule},
            {"rule_type": "folder", "rule_id": folder_rule},
        ]
    )
    session = _session()
    timeline_api.save_timeline_session_override(
        "2026-06-25",
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        1200,
        "contract note",
    )
    timeline_service.get_project_sessions_by_date("2026-06-25")
    statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")

    assert _raw_snapshot() == before
    with get_connection() as conn:
        assignment_projects = {
            row["activity_id"]: row["project_id"]
            for row in conn.execute(
                "SELECT activity_id, project_id FROM activity_project_assignment"
            ).fetchall()
        }
    assert assignment_projects[a1] in {folder_project, keyword_project}
    assert a2 in assignment_projects


def test_session_override_exact_match_consistent_across_surfaces(temp_db):
    project = create_project("Override Project")
    create_closed_activity(start="09:00:00", end="09:30:00")
    create_closed_activity(start="09:30:00", end="10:00:00")
    before = _raw_snapshot()
    session = _session()

    timeline_api.save_timeline_session_override(
        "2026-06-25",
        session["activity_ids"],
        session["activity_member_hash"],
        project,
        1500,
        "exact note",
    )

    timeline_row = timeline_service.get_project_sessions_by_date("2026-06-25")[0]
    overview_row = view_model_service.get_overview_view_model("2026-06-25")["activities"][0]
    stats_project = statistics_service.get_project_stats("2026-06-25", "2026-06-25")[0]
    csv_row = export_service.build_statistics_csv_rows("2026-06-25", "2026-06-25")[0]

    assert timeline_row["project_name"] == "Override Project"
    assert timeline_row["duration_seconds"] == 1500
    assert timeline_row["session_note"] == "exact note"
    assert overview_row["project_name"] == "Override Project"
    assert overview_row["duration_seconds"] == 1500
    assert stats_project["project"] == "Override Project"
    assert stats_project["total_duration"] == 1500
    assert csv_row["project"] == "Override Project"
    assert csv_row["duration_seconds"] == 1500
    assert csv_row["note"] == "exact note"
    assert _raw_snapshot() == before


def test_rule_reorder_conflict_does_not_apply_old_override(temp_db):
    override_project = create_project("Override Project")
    first_project = create_project("First Rule")
    second_project = create_project("Second Rule")
    create_closed_activity(window_title="alpha token", start="09:00:00", end="09:20:00")
    create_closed_activity(window_title="beta token", start="09:20:00", end="09:40:00")
    session = _session()
    timeline_api.save_timeline_session_override(
        "2026-06-25",
        session["activity_ids"],
        session["activity_member_hash"],
        override_project,
        900,
        "old override",
    )

    create_keyword_rule(first_project, "alpha")
    create_keyword_rule(second_project, "beta")
    for aid in session["activity_ids"]:
        assign_project_for_activity(aid)

    sessions = timeline_service.get_project_sessions_by_date("2026-06-25", ensure_context=False)
    assert len(sessions) == 2
    assert all(not row.get("has_project_override") for row in sessions)
    assert all(row.get("session_note") == "" for row in sessions)
    assert {row["project_name"] for row in sessions} == {"First Rule", "Second Rule"}
    assert {row["duration_seconds"] for row in sessions} == {1200}
    with get_connection() as conn:
        states = [row["match_state"] for row in conn.execute("SELECT match_state FROM report_session_operation").fetchall()]
    # Projection getters are read-only; unresolved state is computed in
    # memory and never persisted as a side effect of viewing a report.
    assert states == ["active"]
    stats = statistics_service.get_project_stats("2026-06-25", "2026-06-25", ensure_context=False)
    assert {row["project"] for row in stats} == {"First Rule", "Second Rule"}
    assert all(row["total_duration"] == 1200 for row in stats)


def test_reconfirm_after_conflict_creates_new_exact_override(temp_db):
    override_project = create_project("Override Project")
    reconfirm_project = create_project("Reconfirmed")
    first_project = create_project("First Rule")
    second_project = create_project("Second Rule")
    create_closed_activity(window_title="alpha token", start="09:00:00", end="09:20:00")
    create_closed_activity(window_title="beta token", start="09:20:00", end="09:40:00")
    original = _session()
    timeline_api.save_timeline_session_override(
        "2026-06-25",
        original["activity_ids"],
        original["activity_member_hash"],
        override_project,
        900,
        "old override",
    )
    create_keyword_rule(first_project, "alpha")
    create_keyword_rule(second_project, "beta")
    for aid in original["activity_ids"]:
        assign_project_for_activity(aid)
    split = timeline_service.get_project_sessions_by_date("2026-06-25", ensure_context=False)[0]

    timeline_api.save_timeline_session_override(
        "2026-06-25",
        split["activity_ids"],
        split["activity_member_hash"],
        reconfirm_project,
        600,
        "new override",
    )

    sessions = timeline_service.get_project_sessions_by_date("2026-06-25", ensure_context=False)
    reconfirmed = [row for row in sessions if row.get("has_project_override")]
    assert len(reconfirmed) == 1
    assert reconfirmed[0]["project_name"] == "Reconfirmed"
    assert reconfirmed[0]["duration_seconds"] == 600
    assert reconfirmed[0]["session_note"] == "new override"
    with get_connection() as conn:
        states = sorted(row["match_state"] for row in conn.execute("SELECT match_state FROM report_session_operation").fetchall())
    assert states == ["active", "active"]


def test_forbidden_raw_activity_writes_and_advanced_corrections_static_contract():
    roots = [Path("worktrace/services"), Path("worktrace/api"), Path("worktrace/webview_ui")]
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for root in roots
        for path in root.rglob("*")
        if path.suffix in {".py", ".js"}
    )
    forbidden = [
        "UPDATE activity_log SET project_id",
        "UPDATE activity_log SET auto_classified",
        "UPDATE activity_log SET manual_override",
        "UPDATE activity_log SET note",
        "timeline_correction.js",
        "split_timeline_activity",
        "merge_timeline_activities",
        "hide_timeline_activity",
        "soft_delete_timeline_activity",
        "restore_timeline_activity",
        "update_timeline_activity_time",
        "update_timeline_session_time",
        # Legacy session identity write paths — must never be reintroduced.
        "_resolve_legacy_session_by_activity_ids",
        "_resolve_legacy_session_by_first_activity",
        "_validate_first_activity_id",
        "update_activity_group_project",
        "reclassify_project_activity_summary",
        "reclassify_timeline_session_project(ids,",
        "reclassify_timeline_session_project(activity_ids,",
        "update_timeline_session_note(report_date, ids[0]",
        "update_timeline_session_note_and_duration(report_date, ids[0]",
        "timeline_api.update_timeline_session_note(report_date, ids[0]",
        "timeline_api.update_timeline_session_note_and_duration(report_date, ids[0]",
    ]
    for token in forbidden:
        assert token not in production, (
            f"forbidden legacy session-identity token present in production: {token}"
        )
    # Bridge legacy argument reshuffling — scoped to bridge_timeline.py only,
    # since ``if report_date is None:`` is a legitimate guard in other services
    # (e.g. live_display_service). The spec forbids it only as bridge editing
    # argument reshuffling.
    bridge_timeline = Path("worktrace/webview_ui/bridge_timeline.py").read_text(encoding="utf-8")
    bridge_forbidden = [
        "if project_id is None: project_id = activity_member_hash",
        "if report_date is None:",
    ]
    for token in bridge_forbidden:
        assert token not in bridge_timeline, (
            f"forbidden bridge argument reshuffling in bridge_timeline.py: {token}"
        )
    assert not Path("worktrace/webview_ui/js/timeline_correction.js").exists()


def test_report_session_operations_never_write_raw_or_rule_facts_static_contract():
    source = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "worktrace/services/report_session_operation_service.py",
            "worktrace/services/report_session_operation_engine.py",
        )
    )
    for token in (
        "UPDATE activity_log SET is_deleted",
        "UPDATE activity_log SET is_hidden",
        "DELETE FROM activity_log",
        "UPDATE activity_log SET duration_seconds",
        "UPDATE activity_log SET start_time",
        "UPDATE activity_log SET end_time",
        "UPDATE activity_project_assignment",
        "DELETE FROM activity_project_assignment",
        "DELETE FROM project",
        "DELETE FROM project_rule",
        "DELETE FROM folder_project_rule",
    ):
        assert token not in source
