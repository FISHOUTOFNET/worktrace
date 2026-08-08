from __future__ import annotations

import pytest

from tests.support.activity_factory import create_closed_activity
from tests.support.db_helpers import assign_activity_project, fetch_one, table_count
from worktrace.api import project_api, timeline_api
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection
from worktrace.generation_clock import generation
from worktrace.services import (
    folder_rule_service,
    history_mutation_job_service,
    project_service,
    rule_service,
    statistics_service,
    system_project_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]

DATE = "2026-06-18"


def _activity(project_id: int, start: str, end: str, title: str) -> int:
    activity_id = create_closed_activity(
        day=DATE,
        start=start,
        end=end,
        app_name="Word",
        process_name="winword.exe",
        window_title=title,
    )
    assign_activity_project(activity_id, project_id, manual=True)
    return activity_id


def test_delete_project_physically_removes_identity_rules_and_releases_assignments(temp_db):
    project_id = project_service.create_project("Delete Me")
    keyword_id = rule_service.create_rule("Spec", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(r"D:\\DeleteMe", project_id)
    activity_id = _activity(project_id, "09:00:00", "09:30:00", "Spec.docx")
    before_activity_count = table_count("activity_log")
    uncategorized_id = system_project_service.require_uncategorized_project_id()

    result = project_api.delete_project_for_rules(project_id)

    assert result == {
        "ok": True,
        "project": {"id": project_id, "deleted": True},
    }
    assert fetch_one("SELECT id FROM project WHERE id = ?", (project_id,)) is None
    assert fetch_one("SELECT id FROM project_rule WHERE id = ?", (keyword_id,)) is None
    assert fetch_one("SELECT id FROM folder_project_rule WHERE id = ?", (folder_id,)) is None
    assert table_count("activity_log") == before_activity_count
    assert fetch_one("SELECT id FROM activity_log WHERE id = ?", (activity_id,)) is not None
    assignment = fetch_one(
        """
        SELECT project_id, confidence, source, is_manual,
               suggested_project_name, source_rule_type, source_rule_id
        FROM activity_project_assignment WHERE activity_id = ?
        """,
        (activity_id,),
    )
    assert assignment == {
        "project_id": uncategorized_id,
        "confidence": 100,
        "source": "manual",
        "is_manual": 1,
        "suggested_project_name": None,
        "source_rule_type": None,
        "source_rule_id": None,
    }


def test_delete_project_releases_name_for_new_independent_identity(temp_db):
    old_id = project_service.create_project("Reusable Name")
    rule_service.create_rule("Old Rule", old_id)

    assert project_api.delete_project_for_rules(old_id)["ok"] is True
    new_id = project_service.create_project("Reusable Name")

    assert new_id != old_id
    assert project_service.get_project(old_id) is None
    assert project_service.get_project(new_id)["name"] == "Reusable Name"
    assert all(
        int(row["project_id"]) != new_id
        for row in rule_service.list_rules()
    )


@pytest.mark.parametrize("bad_id", [None, True, False, "1", 1.0, 0, -1, [], {}])
def test_delete_project_rejects_invalid_ids_without_side_effects(temp_db, bad_id):
    project_id = project_service.create_project("Client")

    result = project_api.delete_project_for_rules(bad_id)

    assert result == {"ok": False, "error": "invalid_input"}
    assert project_service.get_project(project_id) is not None


@pytest.mark.parametrize("name", [UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT])
def test_delete_project_rejects_system_special_projects(temp_db, name):
    project_id = (
        system_project_service.require_uncategorized_project_id()
        if name == UNCATEGORIZED_PROJECT
        else system_project_service.require_excluded_project_id()
    )

    result = project_api.delete_project_for_rules(project_id)

    assert result == {"ok": False, "error": "system_project"}
    assert project_service.get_project(project_id) is not None


def test_delete_project_rolls_back_assignment_and_rule_cleanup_if_delete_fails(temp_db):
    project_id = project_service.create_project("Rollback")
    keyword_id = rule_service.create_rule("Spec", project_id)
    activity_id = _activity(project_id, "09:00:00", "09:30:00", "Spec.docx")
    before_catalog = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    before_report = generation(DataGenerationNamespace.REPORT_STRUCTURE)
    with get_connection() as conn:
        conn.execute(
            f"""
            CREATE TRIGGER fail_project_delete
            BEFORE DELETE ON project
            WHEN OLD.id = {int(project_id)}
            BEGIN
                SELECT RAISE(ABORT, 'project delete failed');
            END;
            """
        )

    result = project_api.delete_project_for_rules(project_id)

    assert result == {"ok": False, "error": "operation_failed"}
    assert project_service.get_project(project_id) is not None
    assert fetch_one("SELECT id FROM project_rule WHERE id = ?", (keyword_id,)) is not None
    assignment = fetch_one(
        "SELECT project_id, source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
        (activity_id,),
    )
    assert assignment == {"project_id": project_id, "source": "manual", "is_manual": 1}
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == before_catalog
    assert generation(DataGenerationNamespace.REPORT_STRUCTURE) == before_report


def test_delete_project_fails_closed_while_owned_rule_history_job_is_active(temp_db):
    project_id = project_service.create_project("Busy Project")
    rule_id = rule_service.create_rule("Spec", project_id)
    job = history_mutation_job_service.submit_rule_job(
        "keyword",
        rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=0,
    )
    assert job["status"] in {"pending", "running"}

    result = project_api.delete_project_for_rules(project_id)

    assert result == {"ok": False, "error": "project_busy"}
    assert project_service.get_project(project_id) is not None
    assert fetch_one("SELECT id FROM project_rule WHERE id = ?", (rule_id,)) is not None


def test_deleted_project_override_falls_back_to_uncategorized_but_keeps_other_edits(temp_db):
    base_project = project_service.create_project("Base Project")
    deleted_project = project_service.create_project("Deleted Override")
    _activity(base_project, "09:00:00", "09:30:00", "Draft.docx")
    source = timeline_api.get_project_sessions_by_date(DATE)[0]

    edit = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "delete-project-override",
        deleted_project,
        True,
        720,
        "keep this note",
    )
    assert edit["ok"] is True
    assert project_api.delete_project_for_rules(deleted_project)["ok"] is True

    sessions = timeline_api.get_project_sessions_by_date(DATE)
    assert len(sessions) == 1
    session = sessions[0]
    assert session["project_name"] == UNCATEGORIZED_PROJECT
    assert session["session_note"] == "keep this note"
    assert session["has_duration_override"] is True
    assert session["adjusted_duration_seconds"] == 720
    assert table_count("report_session_operation") == 1


def test_delete_project_preserves_reported_time_as_uncategorized(temp_db):
    retained = project_service.create_project("Retained")
    deleted = project_service.create_project("Deleted")
    _activity(retained, "09:00:00", "09:30:00", "Retained.docx")
    deleted_activity = _activity(deleted, "09:30:00", "10:00:00", "Deleted.docx")

    before = statistics_service.get_summary(DATE, DATE)
    assert project_api.delete_project_for_rules(deleted)["ok"] is True
    after = statistics_service.get_summary(DATE, DATE)
    released = fetch_one(
        "SELECT project_id, source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
        (deleted_activity,),
    )

    assert released == {
        "project_id": system_project_service.require_uncategorized_project_id(),
        "source": "manual",
        "is_manual": 1,
    }
    assert before["total_duration"] == 3600
    assert after["total_duration"] == 3600
    assert after["effective_duration"] == 3600
    assert after["classified_duration"] == 1800
    assert after["uncategorized_duration"] == 1800
