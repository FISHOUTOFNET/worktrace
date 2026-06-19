import pytest

from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.services import activity_service, folder_rule_service, project_service, resource_service, rule_service
from worktrace.ui.project_rules_view import ProjectRulesView, _project_binding_text


def test_project_rules_view_combines_file_folder_and_keyword_rules(temp_db):
    project_id = project_service.create_project("Client")
    resource_service.create_or_update_file_default("D:\\Client\\Spec.docx", project_id)
    folder_rule_service.create_or_update_folder_rule("D:\\Client", project_id)
    rule_service.create_rule("Spec", project_id)
    view = object.__new__(ProjectRulesView)

    rules = ProjectRulesView._combined_rules(view)

    assert {rule["kind"] for rule in rules} == {"file", "folder", "keyword"}


def test_project_binding_text_includes_all_rule_types():
    text = _project_binding_text(
        {
            "folder_rules": [{"folder_path": "D:\\Client"}],
            "file_defaults": [{"full_path": "D:\\Client\\Spec.docx"}],
            "keyword_rules": [{"keyword": "Spec"}],
        }
    )

    assert "文件：D:\\Client\\Spec.docx" in text
    assert "文件夹：D:\\Client" in text
    assert "关键词：Spec" in text


def test_delete_project_deletes_project_and_clears_associated_rules(temp_db):
    project_id = project_service.create_project("Client")
    resource_service.create_or_update_file_default("D:\\Client\\Spec.docx", project_id)
    folder_rule_service.create_or_update_folder_rule("D:\\Client", project_id)
    rule_service.create_rule("Spec", project_id)

    project_service.delete_project(project_id)

    assert project_service.get_project(project_id) is None
    assert "Client" not in [project["name"] for project in project_service.list_user_projects()]
    assert resource_service.list_file_defaults() == []
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
