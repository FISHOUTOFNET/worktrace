from worktrace.services import folder_rule_service, project_service, resource_service, rule_service
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
