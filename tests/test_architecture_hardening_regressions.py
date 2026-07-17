from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.support.activity_factory import create_closed_activity, create_open_activity
from worktrace.api import timeline_api
from worktrace.db import get_connection, now_str
from worktrace.mutation_effects import MutationEffect, mutation_effects
from worktrace.services import (
    database_maintenance_service,
    folder_rule_service,
    privacy_gate_service,
    project_service,
    report_revision_service,
    report_session_operation_service,
    rule_batch_service,
    rule_service,
    statistics_service,
    view_model_service,
)
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.statistics_projection import build_statistics_projection
from worktrace.webview_ui.bridge import WebViewBridge
from worktrace.write_gate import DATABASE_WRITE_GATE

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-15"


def _activity(start, end, *, project_id=None, status="normal", app="Word"):
    common = {
        "app_name": app,
        "process_name": app.lower() + ".exe",
        "window_title": app,
        "project_id": project_id,
        "status": status,
    }
    if end is None:
        return create_open_activity(start_time=f"{DATE} {start}", **common)
    return create_closed_activity(day=DATE, start=start, end=end, **common)


def test_clear_all_preserves_installation_privacy_but_pauses_sensitive_runtime(temp_db):
    privacy_gate_service.accept_privacy_notice()
    project_service.create_project("Client")
    database_maintenance_service.clear_all_live_data()
    assert privacy_gate_service.is_privacy_notice_accepted() is True
    with get_connection() as conn:
        settings = {
            row["key"]: row["value"]
            for row in conn.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?, ?)",
                ("user_paused", "collector_status", "clipboard_capture_enabled"),
            ).fetchall()
        }
    assert settings == {
        "user_paused": "true",
        "collector_status": "paused",
        "clipboard_capture_enabled": "false",
    }


def test_structure_revision_ignores_open_duration_but_tracks_structure(temp_db):
    activity_id = _activity("09:00:00", None)
    before = report_revision_service.get_report_structure_revision(DATE)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = ?, updated_at = ? WHERE id = ?",
            (777, now_str(), activity_id),
        )
    assert report_revision_service.get_report_structure_revision(DATE) == before
    with mutation_effects(MutationEffect.REPORT_STRUCTURE):
        with get_connection() as conn:
            conn.execute(
                "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
                ("idle", now_str(), activity_id),
            )
    assert report_revision_service.get_report_structure_revision(DATE) != before


def test_structure_revision_tracks_resource_display_facts(temp_db):
    activity_id = _activity("09:00:00", None)
    before = report_revision_service.get_report_structure_revision(DATE)
    with mutation_effects(MutationEffect.REPORT_STRUCTURE):
        with get_connection() as conn:
            conn.execute(
                "UPDATE activity_resource SET display_name = ? WHERE activity_id = ?",
                ("Renamed.docx", activity_id),
            )
    assert report_revision_service.get_report_structure_revision(DATE) != before


def test_export_revision_is_exact_closed_record_revision(temp_db):
    project_id = project_service.create_project("Client")
    _activity("09:00:00", "09:30:00", project_id=project_id)
    first = build_statistics_projection(build_visible_snapshot(DATE, DATE))
    open_id = _activity("10:00:00", None, project_id=project_id)
    second = build_statistics_projection(build_visible_snapshot(DATE, DATE))
    assert second.export_revision == first.export_revision
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = ?, updated_at = ? WHERE id = ?",
            (3600, now_str(), open_id),
        )
    third = build_statistics_projection(build_visible_snapshot(DATE, DATE))
    assert third.export_revision == first.export_revision


def test_project_and_app_counts_exclude_privacy_and_uncategorized_buckets(temp_db):
    project_id = project_service.create_project("Client")
    _activity("09:00:00", "09:30:00", project_id=project_id)
    _activity("10:00:00", "10:10:00")
    _activity("11:00:00", "11:05:00", status="excluded", app="Secret")
    summary = statistics_service.get_statistics_export_summary(DATE, DATE)
    names = {row["display_name"] for row in summary["by_project"]}
    assert {"Client", "未归类", "已排除"}.issubset(names)
    assert summary["project_count"] == 1
    assert summary["app_count"] == 1
    assert {
        row["display_name"]
        for row in summary["by_project"]
        if row["is_concrete_project"]
    } == {"Client"}


def test_overview_counts_standalone_excluded_without_showing_it_in_recent(temp_db):
    _activity("11:00:00", "11:05:00", status="excluded", app="Secret")
    payload = view_model_service.get_overview_view_model(DATE)
    assert payload["today_total_seconds"] == 300
    assert all(
        str(row.get("row_kind") or "") != "standalone_status"
        for row in payload.get("activities") or []
    )


def test_persisted_open_session_allows_project_and_note_but_not_duration(temp_db):
    first_project = project_service.create_project("A")
    second_project = project_service.create_project("B")
    open_id = _activity("09:00:00", None, project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "open-project-note-edit",
        second_project,
        None,
        "open memo",
    )
    assert result["ok"] is True
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert updated["project_id"] == second_project
    assert updated["session_note"] == "open memo"
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id, source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (open_id,),
        ).fetchone()
    assert assignment is not None
    assert int(assignment["project_id"]) == second_project
    assert assignment["source"] == "manual"
    assert int(assignment["is_manual"]) == 1
    with pytest.raises(Exception):
        timeline_api.save_timeline_session_edit(
            DATE,
            updated["projection_instance_key"],
            updated["projection_revision"],
            "open-duration-rejected",
            None,
            600,
            "open memo",
        )


def test_persisted_open_session_project_only_edit_is_effective(temp_db):
    first_project = project_service.create_project("ProjectOnlyA")
    second_project = project_service.create_project("ProjectOnlyB")
    _activity("10:00:00", None, project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "open-project-only-edit",
        second_project,
        None,
        "",
    )
    assert result["ok"] is True
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert int(updated["project_id"]) == second_project


def test_open_session_no_op_rolls_back_manual_assignment(temp_db):
    first_project = project_service.create_project("RollbackA")
    second_project = project_service.create_project("RollbackB")
    open_id = _activity("11:00:00", None, project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    with patch.object(
        report_session_operation_service,
        "_expected_effect",
        return_value=False,
    ):
        result = report_session_operation_service.edit_session(
            DATE,
            source["projection_instance_key"],
            source["projection_revision"],
            "open-project-forced-no-op",
            project_id=second_project,
            adjusted_duration_seconds=None,
            note="forced no-op",
        )
    assert result.outcome_type == "no_op"
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id, source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (open_id,),
        ).fetchone()
    assert assignment is not None
    assert int(assignment["project_id"]) == first_project
    assert assignment["source"] == "manual"
    assert int(assignment["is_manual"]) == 1


def test_rule_batch_refreshes_generation_before_write_lock(temp_db):
    activity_id = _activity("13:00:00", "13:10:00")
    project_id = project_service.create_project("GenerationTarget")
    rule_id = rule_service.create_rule("Word", project_id)
    DATABASE_WRITE_GATE.note_current_thread_read()
    thread_errors: list[BaseException] = []

    def rotate_generation() -> None:
        try:
            with DATABASE_WRITE_GATE.acquire():
                pass
        except BaseException as exc:  # pragma: no cover
            thread_errors.append(exc)

    thread = threading.Thread(target=rotate_generation)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert thread_errors == []
    result = rule_batch_service.preview_rules_batch_impact(
        [{"kind": "keyword", "id": rule_id}]
    )
    assert result["matched_activity_ids"] == [activity_id]


def test_folder_rule_preview_uses_persisted_resource_path(temp_db, tmp_path: Path):
    project_id = project_service.create_project("FolderTarget")
    folder = tmp_path / "Matter"
    folder.mkdir()
    file_path = folder / "brief.docx"
    file_path.write_text("x", encoding="utf-8")
    _activity("14:00:00", "14:10:00")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project_id)
    preview = rule_batch_service.preview_rules_batch_impact(
        [{"kind": "folder", "id": rule_id}]
    )
    assert isinstance(preview["matched_activity_ids"], list)


def test_bridge_shipping_surface_stays_fixed(temp_db):
    bridge = WebViewBridge()
    shipping = bridge.shipping_api
    assert not hasattr(shipping, "set_window")
    assert not hasattr(shipping, "application_control")
    assert json.dumps(bridge.get_status(), ensure_ascii=False)
