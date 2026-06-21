import pytest

from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.services import activity_service, folder_rule_service, project_service, rule_service
from worktrace.ui.project_rule_dialog import PROJECT_MODE_NEW
from worktrace.ui.project_rules_view import ProjectRulesView, _project_binding_text


class FakeRuleWidget:
    def __init__(self, name=""):
        self.name = name
        self.destroyed = False
        self.grid_calls = []
        self.grid_removed = False

    def grid(self, *args, **kwargs):
        self.grid_calls.append((args, kwargs))
        self.grid_removed = False

    def grid_remove(self):
        self.grid_removed = True

    def destroy(self):
        self.destroyed = True


class FakeCanvas:
    def __init__(self, position=0.0):
        self.position = position
        self.moves = []

    def yview(self):
        return (self.position, 1.0)

    def yview_moveto(self, position):
        self.position = position
        self.moves.append(position)


class FakeScroll:
    def __init__(self, position=0.0):
        self._parent_canvas = FakeCanvas(position)


def test_project_rules_view_combines_folder_and_keyword_rules(temp_db):
    project_id = project_service.create_project("Client")
    folder_rule_service.create_or_update_folder_rule("D:\\Client", project_id)
    rule_service.create_rule("Spec", project_id)
    view = object.__new__(ProjectRulesView)

    rules = ProjectRulesView._combined_rules(view)

    assert {rule["kind"] for rule in rules} == {"folder", "keyword"}


def test_project_rules_create_project_opens_project_only_dialog(monkeypatch):
    calls = []
    view = object.__new__(ProjectRulesView)

    monkeypatch.setattr(
        "worktrace.ui.project_rules_view.open_project_rule_dialog",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    ProjectRulesView.create_project(view)

    assert calls[0][1]["initial_project_mode"] == PROJECT_MODE_NEW
    assert calls[0][1]["initial_create_rule"] is False


def test_project_rules_project_rule_button_locks_existing_project(monkeypatch):
    calls = []
    view = object.__new__(ProjectRulesView)

    monkeypatch.setattr(
        "worktrace.ui.project_rules_view.open_project_rule_dialog",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    ProjectRulesView.open_new_rule_dialog(view, initial_project_name="Client")

    assert calls[0][1]["initial_project_name"] == "Client"
    assert calls[0][1]["lock_project"] is True


def test_project_rules_refresh_reuses_unchanged_rows_and_restores_scroll(monkeypatch):
    first_projects = [
        _binding(1, "A", "old", enabled=1),
        _binding(2, "B", "", enabled=1),
    ]
    second_projects = [
        _binding(1, "A", "old", enabled=0),
        _binding(2, "B", "", enabled=1),
    ]
    calls = []
    view = object.__new__(ProjectRulesView)
    view._rules_signature = None
    view._project_widgets = {}
    view._empty_widget = None
    view.rules_frame = FakeRuleWidget("rules")
    view.scroll = FakeScroll(position=0.42)
    view.after_idle = lambda callback: callback()

    monkeypatch.setattr(project_service, "list_project_bindings", lambda: first_projects)
    monkeypatch.setattr(
        ProjectRulesView,
        "_project_group",
        lambda _self, _parent, _row_index, project: calls.append(project["id"]) or FakeRuleWidget(project["name"]),
    )

    ProjectRulesView.refresh_rules(view)
    unchanged = view._project_widgets[2]["widget"]
    changed = view._project_widgets[1]["widget"]

    monkeypatch.setattr(project_service, "list_project_bindings", lambda: second_projects)
    ProjectRulesView.refresh_rules(view)

    assert calls == [1, 2, 1]
    assert changed.destroyed is True
    assert view._project_widgets[2]["widget"] is unchanged
    assert unchanged.destroyed is False
    assert view.scroll._parent_canvas.moves[-1] == 0.42


def test_project_binding_text_includes_all_rule_types():
    text = _project_binding_text(
        {
            "folder_rules": [{"folder_path": "D:\\Client"}],
            "keyword_rules": [{"keyword": "Spec"}],
        }
    )

    assert "文件夹：D:\\Client" in text
    assert "关键词：Spec" in text


def test_project_rules_copy_text_includes_project_description(temp_db):
    project_service.create_project("Client", "billable")
    view = object.__new__(ProjectRulesView)

    text = ProjectRulesView.copy_page_text(view)

    assert "Client (billable)" in text


def _binding(project_id, name, description="", enabled=1):
    return {
        "id": project_id,
        "name": name,
        "description": description,
        "enabled": enabled,
        "created_by": "user",
        "folder_rules": [],
        "keyword_rules": [],
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
