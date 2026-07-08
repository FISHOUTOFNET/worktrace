"""Service-layer regression tests for the Project Rules domain.

The six ``ProjectRulesView`` widget-wiring tests and the two
``worktrace.ui.*`` imports were removed. The five service-layer tests below
exercise ``project_service`` /
``folder_rule_service`` / ``rule_service`` / ``activity_service`` directly and
do not depend on any UI module. They are kept because they lock behavior that
is not fully covered by the API-facade tests in
``test_project_rules_project_lifecycle.py`` (notably the direct
``project_service.delete_project`` cascade, which is intentionally not exposed
through the ``*_for_rules`` API facades).
"""

import pytest

from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.db import get_connection
from worktrace.services import activity_service, folder_rule_service, project_service, rule_service

pytestmark = [pytest.mark.db]


def test_project_bindings_readonly_returns_grouped_user_and_excluded_projects(temp_db):
    user_project = project_service.create_project("Client")
    other_project = project_service.create_project("Other")
    excluded_project = project_service.get_or_create_excluded_project()
    folder_rule_service.create_or_update_folder_rule(r"D:\Client", user_project)
    rule_service.create_rule("Spec", user_project)
    folder_rule_service.create_or_update_folder_rule(r"D:\Private", excluded_project)

    before_counts = _table_counts()

    projects = project_service.list_project_bindings()

    after_counts = _table_counts()
    assert after_counts == before_counts
    assert [project["name"] for project in projects] == [
        EXCLUDED_PROJECT,
        "Client",
        "Other",
    ]
    by_name = {project["name"]: project for project in projects}
    assert len(by_name["Client"]["folder_rules"]) == 1
    assert by_name["Client"]["folder_rules"][0]["folder_path"] == r"D:\Client"
    assert len(by_name["Client"]["keyword_rules"]) == 1
    assert by_name["Client"]["keyword_rules"][0]["keyword"] == "Spec"
    assert len(by_name[EXCLUDED_PROJECT]["folder_rules"]) == 1
    assert by_name[EXCLUDED_PROJECT]["folder_rules"][0]["folder_path"] == r"D:\Private"
    assert by_name["Other"]["folder_rules"] == []
    assert by_name["Other"]["keyword_rules"] == []


def _table_counts():
    with get_connection() as conn:
        return {
            "project": conn.execute("SELECT COUNT(*) FROM project").fetchone()[0],
            "folder_project_rule": conn.execute(
                "SELECT COUNT(*) FROM folder_project_rule"
            ).fetchone()[0],
            "project_rule": conn.execute("SELECT COUNT(*) FROM project_rule").fetchone()[0],
        }


def test_delete_project_deletes_project_and_clears_associated_rules(temp_db):
    project_id = project_service.create_project("Client")
    folder_rule_service.create_or_update_folder_rule("D:\\Client", project_id)
    rule_service.create_rule("Spec", project_id)

    project_service.delete_project(project_id)

    assert project_service.get_project(project_id) is None
    assert "Client" not in [project["name"] for project in project_service.list_user_projects()]
    assert folder_rule_service.list_folder_rules() == []
    assert rule_service.list_rules() == []


def test_project_can_be_edited_and_disabled(temp_db):
    project_id = project_service.create_project("Client", "old")

    project_service.update_project(project_id, "Client Renamed", "new")
    project_service.set_project_enabled(project_id, False)

    project = project_service.get_project(project_id)
    assert project["name"] == "Client Renamed"
    assert project["description"] == "new"
    assert project["enabled"] == 0


def test_system_projects_are_protected_from_editing_and_uncategorized_disable(temp_db):
    uncategorized_id = project_service.get_or_create_uncategorized_project()
    excluded_id = project_service.get_or_create_excluded_project()

    with pytest.raises(ValueError):
        project_service.update_project(excluded_id, "Nope")
    with pytest.raises(ValueError):
        project_service.set_project_enabled(uncategorized_id, False)

    assert project_service.get_project(excluded_id)["name"] == EXCLUDED_PROJECT


def test_disabled_project_does_not_auto_classify_keyword_rule(temp_db):
    project_id = project_service.create_project("Client")
    rule_service.create_rule("AcmeOnly", project_id)
    project_service.set_project_enabled(project_id, False)

    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "AcmeOnly Spec.docx - Word",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity_id)

    activity = activity_service.get_activity(activity_id)
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
