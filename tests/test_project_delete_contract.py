from __future__ import annotations

import pytest

from tests.support.activity_factory import create_closed_activity
from tests.support.db_helpers import assign_activity_project, fetch_one, table_count

from worktrace.api import project_api
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.db import get_connection
from worktrace.services import (
    export_service,
    folder_rule_service,
    project_service,
    report_session_operation_service,
    rule_service,
    statistics_service,
    timeline_service,
)
from worktrace.webview_ui.bridge_rules import ProjectRulesBridgeMixin

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _project_row(project_id: int) -> dict:
    row = fetch_one("SELECT * FROM project WHERE id = ?", (project_id,))
    assert row is not None
    return row


def _activity(project_id: int, start: str, end: str, title: str, app: str = "Word") -> int:
    aid = create_closed_activity(
        day="2026-06-18",
        start=start,
        end=end,
        app_name=app,
        process_name=f"{app.casefold()}.exe",
        window_title=title,
    )
    assign_activity_project(aid, project_id, manual=True)
    return aid


def _edit_session_project(report_date: str, session: dict, project_id: int) -> None:
    count = getattr(_edit_session_project, "_count", 0) + 1
    setattr(_edit_session_project, "_count", count)
    report_session_operation_service.edit_session(
        report_date,
        session["projection_instance_key"],
        session["projection_revision"],
        f"test-project-delete-{count}",
        project_id=project_id,
        adjusted_duration_seconds=None,
        note="",
    )


def test_delete_project_soft_deletes_and_keeps_facts_rules_and_bindings_hidden(temp_db):
    project_id = project_service.create_project("Delete Me")
    keyword_id = rule_service.create_rule("Spec", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(r"D:\DeleteMe", project_id)
    activity_id = _activity(project_id, "09:00:00", "09:30:00", "Spec.docx")
    before_counts = {
        "project": table_count("project"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "keyword": table_count("project_rule"),
        "folder": table_count("folder_project_rule"),
    }

    result = project_api.delete_project_for_rules(project_id)

    assert result["ok"] is True
    assert result["project"]["deleted"] is True
    row = _project_row(project_id)
    assert row["is_deleted"] == 1
    assert row["is_archived"] == 1
    assert row["enabled"] == 0
    assert table_count("project") == before_counts["project"]
    assert table_count("activity_log") == before_counts["activity"]
    assert table_count("activity_project_assignment") == before_counts["assignment"]
    assert table_count("project_rule") == before_counts["keyword"]
    assert table_count("folder_project_rule") == before_counts["folder"]
    assert fetch_one("SELECT id FROM project_rule WHERE id = ?", (keyword_id,)) is not None
    assert fetch_one("SELECT id FROM folder_project_rule WHERE id = ?", (folder_id,)) is not None
    assert fetch_one("SELECT id FROM activity_log WHERE id = ?", (activity_id,)) is not None
    assert project_id not in {int(row["id"]) for row in project_service.list_project_bindings()}
    assert project_id not in {int(row["id"]) for row in project_service.list_rule_target_projects()}
    assert project_id not in {int(row["id"]) for row in project_service.list_selectable_projects()}


@pytest.mark.parametrize("bad_id", [None, True, False, "1", 1.0, 0, -1, [], {}])
def test_delete_project_rejects_invalid_ids_without_side_effects(temp_db, bad_id):
    project_id = project_service.create_project("Client")
    result = project_api.delete_project_for_rules(bad_id)
    assert result == {"ok": False, "error": "invalid_input"}
    assert _project_row(project_id)["is_deleted"] == 0


@pytest.mark.parametrize("name", [UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT])
def test_delete_project_rejects_system_special_projects(temp_db, name):
    project_id = (
        project_service.get_or_create_uncategorized_project()
        if name == UNCATEGORIZED_PROJECT
        else project_service.get_or_create_excluded_project()
    )
    result = project_api.delete_project_for_rules(project_id)
    assert result == {"ok": False, "error": "system_project"}
    assert _project_row(project_id)["is_deleted"] == 0


def test_delete_project_update_failure_rolls_back_without_cache_invalidation(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
    calls = {"invalidate": 0}

    def spy():
        calls["invalidate"] += 1

    monkeypatch.setattr(project_service, "_invalidate_project_lifecycle_caches", spy)
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_project_soft_delete
            BEFORE UPDATE OF is_deleted ON project
            WHEN NEW.is_deleted = 1
            BEGIN
                SELECT RAISE(ABORT, 'soft delete failed');
            END;
            """
        )

    result = project_api.delete_project_for_rules(project_id)

    assert result == {"ok": False, "error": "operation_failed"}
    row = _project_row(project_id)
    assert row["is_deleted"] == 0
    assert row["is_archived"] == 0
    assert row["enabled"] == 1
    assert calls["invalidate"] == 0


def test_deleted_project_session_is_suppressed_without_merging_surrounding_sessions(temp_db):
    project_a = project_service.create_project("Project A")
    deleted = project_service.create_project("Deleted Project")
    first_a = _activity(project_a, "09:00:00", "09:30:00", "A1.docx")
    deleted_activity = _activity(deleted, "09:30:00", "10:00:00", "Deleted.docx")
    second_a = _activity(project_a, "10:00:00", "10:30:00", "A2.docx")

    project_service.soft_delete_project(deleted)

    sessions = timeline_service.get_project_sessions_by_range("2026-06-18", "2026-06-18")
    names = [session["project_name"] for session in sessions]
    assert names.count("Project A") == 2
    assert "Deleted Project" not in repr(sessions)
    assert all(deleted_activity not in session.get("activity_ids", []) for session in sessions)
    assert sorted([session["activity_ids"] for session in sessions]) == [[first_a], [second_a]]


def test_deleted_project_override_semantics(temp_db):
    valid = project_service.create_project("Valid Project")
    deleted = project_service.create_project("Deleted Project")
    deleted_activity = _activity(deleted, "09:00:00", "09:30:00", "Deleted.docx")
    valid_activity = _activity(valid, "10:00:00", "10:30:00", "Valid.docx")

    deleted_session = timeline_service.get_project_sessions_by_range("2026-06-18", "2026-06-18")[1]
    _edit_session_project("2026-06-18", deleted_session, valid)
    valid_session = timeline_service.get_project_sessions_by_range("2026-06-18", "2026-06-18")[0]
    _edit_session_project("2026-06-18", valid_session, deleted)

    project_service.soft_delete_project(deleted)

    sessions = timeline_service.get_project_sessions_by_range("2026-06-18", "2026-06-18")
    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "Valid Project"
    assert sessions[0]["activity_ids"] == [deleted_activity]
    assert valid_activity not in sessions[0]["activity_ids"]
    assert table_count("report_session_operation") == 2
    assert "Deleted Project" not in repr(sessions)


def test_deleted_project_is_removed_from_statistics_and_csv_export(temp_db):
    project_a = project_service.create_project("Project A")
    deleted = project_service.create_project("Deleted Project")
    _activity(project_a, "09:00:00", "09:30:00", "A1.docx", app="Word")
    _activity(deleted, "09:30:00", "10:00:00", "Deleted.docx", app="Excel")
    _activity(project_a, "10:00:00", "10:30:00", "A2.docx", app="Word")

    before = statistics_service.get_summary("2026-06-18", "2026-06-18")
    project_service.soft_delete_project(deleted)
    after = statistics_service.get_summary("2026-06-18", "2026-06-18")
    project_stats = statistics_service.get_project_stats("2026-06-18", "2026-06-18")
    export_summary = statistics_service.get_statistics_export_summary("2026-06-18", "2026-06-18")
    csv_rows = export_service.build_statistics_csv_rows("2026-06-18", "2026-06-18")

    assert before["total_duration"] == 5400
    assert after["total_duration"] == 3600
    assert after["effective_duration"] == 3600
    assert after["classified_duration"] == 3600
    assert after["uncategorized_duration"] == 0
    assert {row["project"] for row in project_stats} == {"Project A"}
    assert export_summary["total_duration_seconds"] == 3600
    assert export_summary["activity_count"] == 2
    assert export_summary["project_count"] == 1
    assert "Deleted Project" not in repr(csv_rows)
    assert sum(int(row["duration_seconds"]) for row in csv_rows) == 3600


def test_archived_project_history_remains_reportable_as_delete_contrast(temp_db):
    archived = project_service.create_project("Archived Project")
    _activity(archived, "09:00:00", "09:30:00", "Archived.docx")

    project_api.archive_project_for_rules(archived)

    assert archived not in {int(row["id"]) for row in project_service.list_rule_target_projects()}
    sessions = timeline_service.get_project_sessions_by_range("2026-06-18", "2026-06-18")
    assert [session["project_name"] for session in sessions] == ["Archived Project"]
    assert statistics_service.get_summary("2026-06-18", "2026-06-18")["total_duration"] == 1800


def test_bridge_delete_project_uses_delete_specific_safe_messages(monkeypatch):
    bridge = ProjectRulesBridgeMixin()

    for code, message in {
        "invalid_input": "操作无效",
        "not_found": "项目不存在",
        "system_project": "系统项目不能删除",
        "operation_failed": "删除项目失败",
        "unknown": "删除项目失败",
    }.items():
        monkeypatch.setattr(
            "worktrace.webview_ui.bridge_rules.project_api.delete_project_for_rules",
            lambda project_id, code=code: {"ok": False, "error": code},
        )
        result = bridge.delete_project_for_rules(1)
        assert result == {"ok": False, "error": message}
        assert "归档项目失败" not in repr(result)
