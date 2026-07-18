"""Project lifecycle API, generation, and isolation contracts."""

from __future__ import annotations

import json

import pytest

from worktrace.services import system_project_service

from tests.support import activity_factory as activity_service
from tests.support.db_helpers import table_count
from worktrace.api import project_api, rule_api
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection
from worktrace.generation_clock import generation
from worktrace.services import (
    folder_rule_service,
    history_mutation_job_service,
    privacy_service,
    project_inference_service,
    project_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def test_project_bindings_include_domain_owned_lifecycle_capabilities(temp_db):
    user_project = project_service.create_project("Capability Project")
    excluded_project = system_project_service.require_excluded_project_id()

    bindings = {
        int(project["id"]): project
        for project in project_service.list_project_bindings()
    }

    assert {
        key: bindings[user_project][key]
        for key in (
            "is_system",
            "is_excluded",
            "editable",
            "can_toggle",
            "can_archive",
        )
    } == {
        "is_system": False,
        "is_excluded": False,
        "editable": True,
        "can_toggle": True,
        "can_archive": True,
    }
    assert {
        key: bindings[excluded_project][key]
        for key in (
            "is_system",
            "is_excluded",
            "editable",
            "can_toggle",
            "can_archive",
        )
    } == {
        "is_system": True,
        "is_excluded": True,
        "editable": False,
        "can_toggle": False,
        "can_archive": False,
    }


def _row(project_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project WHERE id = ?",
            (project_id,),
        ).fetchone()
    return dict(row) if row else None


def _assert_project_payload(payload: dict) -> None:
    assert set(payload) == {
        "id",
        "name",
        "description",
        "language",
        "enabled",
        "archived",
    }
    assert type(payload["id"]) is int
    assert type(payload["name"]) is str
    assert type(payload["description"]) is str
    assert type(payload["language"]) is str
    assert type(payload["enabled"]) is bool
    assert type(payload["archived"]) is bool


def test_create_project_trims_fields_and_defaults_language(temp_db):
    before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    result = project_api.create_project_for_rules(
        "  Client  ",
        "  Billable work  ",
        "   ",
    )

    assert result["ok"] is True
    _assert_project_payload(result["project"])
    assert result["project"] == {
        "id": result["project"]["id"],
        "name": "Client",
        "description": "Billable work",
        "language": "中文",
        "enabled": True,
        "archived": False,
    }
    row = _row(result["project"]["id"])
    assert row["created_by"] == "user"
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == before + 1


@pytest.mark.parametrize(
    ("name", "description", "language"),
    [
        (None, "", "中文"),
        (True, "", "中文"),
        (1, "", "中文"),
        ("", "", "中文"),
        ("   ", "", "中文"),
        ("Client", None, "中文"),
        ("Client", 1, "中文"),
        ("Client", "", None),
        ("Client", "", True),
    ],
)
def test_create_rejects_invalid_inputs(temp_db, name, description, language):
    assert project_api.create_project_for_rules(name, description, language) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_create_rejects_duplicates_and_reserved_system_names(temp_db):
    project_api.create_project_for_rules("Client", "")
    system_project_service.require_uncategorized_project_id()
    system_project_service.require_excluded_project_id()

    for name in ("Client", "  Client  "):
        assert project_api.create_project_for_rules(name, "") == {
            "ok": False,
            "error": "duplicate_project",
        }
    for name in (UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT):
        assert project_api.create_project_for_rules(name, "") == {
            "ok": False,
            "error": "system_project",
        }


def test_update_project_preserves_state_and_identity(temp_db):
    project_id = project_service.create_project("Client", "old", "中文")
    project_service.set_project_enabled(project_id, False)
    before = _row(project_id)

    result = project_api.update_project_for_rules(
        project_id,
        "  Renamed  ",
        "  new desc  ",
        " 英语 ",
    )

    assert result["ok"] is True
    assert result["project"] == {
        "id": project_id,
        "name": "Renamed",
        "description": "new desc",
        "language": "英语",
        "enabled": False,
        "archived": False,
    }
    after = _row(project_id)
    assert after["created_by"] == before["created_by"]
    assert after["created_at"] == before["created_at"]
    assert after["enabled"] == 0


@pytest.mark.parametrize("project_id", [True, "1", 1.5, 0, -1, None, [], {}])
def test_update_toggle_archive_reject_invalid_ids(temp_db, project_id):
    assert project_api.update_project_for_rules(project_id, "Name", "") == {
        "ok": False,
        "error": "invalid_input",
    }
    assert project_api.set_project_enabled_for_rules(project_id, True) == {
        "ok": False,
        "error": "invalid_input",
    }
    assert project_api.archive_project_for_rules(project_id) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_update_rejects_duplicate_other_project(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")

    assert project_api.update_project_for_rules(project_b, "A", "") == {
        "ok": False,
        "error": "duplicate_project",
    }
    assert _row(project_a)["name"] == "A"
    assert _row(project_b)["name"] == "B"


def test_system_projects_cannot_be_updated_toggled_or_archived(temp_db):
    for project_id in (
        system_project_service.require_uncategorized_project_id(),
        system_project_service.require_excluded_project_id(),
    ):
        assert project_api.update_project_for_rules(project_id, "Renamed", "") == {
            "ok": False,
            "error": "system_project",
        }
        assert project_api.set_project_enabled_for_rules(project_id, True) == {
            "ok": False,
            "error": "system_project",
        }
        assert project_api.archive_project_for_rules(project_id) == {
            "ok": False,
            "error": "system_project",
        }


def test_toggle_and_archive_publish_catalog_generation(temp_db):
    project_id = project_service.create_project("Client")
    first = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    disabled = project_api.set_project_enabled_for_rules(project_id, False)
    second = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    archived = project_api.archive_project_for_rules(project_id)
    third = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    assert disabled["project"]["enabled"] is False
    assert second == first + 1
    assert archived["project"]["archived"] is True
    assert third == second + 1


def test_project_state_refreshes_rule_caches_via_generation(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )
    assert project_inference_service._enabled_keyword_rules()
    assert folder_rule_service.find_matching_folder_rule(r"D:\Client\Doc.docx")

    result = project_api.set_project_enabled_for_rules(project_id, False)

    assert result["ok"] is True
    assert project_inference_service._enabled_keyword_rules() == []
    assert folder_rule_service.find_matching_folder_rule(r"D:\Client\Doc.docx") is None
    assert any(int(row["id"]) == keyword_id for row in rule_service.list_rules())
    assert any(int(row["id"]) == folder_id for row in folder_rule_service.list_folder_rules())


def test_excluded_project_toggle_publishes_privacy_generation(temp_db):
    excluded_id = system_project_service.require_excluded_project_id()
    rule_service.create_rule("Secret", excluded_id)
    before = generation(DataGenerationNamespace.PRIVACY_CATALOG)

    result = project_api.set_excluded_rules_enabled(True)

    assert result["ok"] is True
    assert generation(DataGenerationNamespace.PRIVACY_CATALOG) == before + 1
    assert privacy_service._exclude_rules()["keywords"] == [{"keyword": "Secret"}]


def test_project_lifecycle_preserves_rules_and_history(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
    rule_service.create_rule("Spec", project_id)
    folder_rule_service.create_or_update_folder_rule(r"D:\Client", project_id)
    activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project_id,
    )
    before = {
        "keyword": table_count("project_rule"),
        "folder": table_count("folder_project_rule"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "operation": table_count("report_session_operation"),
    }

    def fail_job(*args, **kwargs):
        raise AssertionError("project lifecycle must not submit a history job")

    monkeypatch.setattr(history_mutation_job_service, "submit_rule_job", fail_job)
    assert project_api.update_project_for_rules(project_id, "Renamed", "")["ok"] is True
    assert project_api.set_project_enabled_for_rules(project_id, False)["ok"] is True
    assert project_api.archive_project_for_rules(project_id)["ok"] is True

    assert {
        "keyword": table_count("project_rule"),
        "folder": table_count("folder_project_rule"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "operation": table_count("report_session_operation"),
    } == before


def test_service_exception_is_privacy_safe(temp_db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("SELECT traceback window_title clipboard C:\\Secret")

    monkeypatch.setattr(project_service, "create_project", boom)
    monkeypatch.setattr(project_service, "get_project_by_name", lambda _name: None)
    result = project_api.create_project_for_rules("Client", "")

    assert result == {"ok": False, "error": "operation_failed"}
    serialized = json.dumps(result).casefold()
    for forbidden in ("select", "traceback", "window_title", "clipboard", "secret"):
        assert forbidden not in serialized


def test_existing_rule_crud_remains_available(temp_db):
    project_id = project_api.create_project_for_rules("Client", "")["project"]["id"]
    keyword = rule_api.create_project_keyword_rule(project_id, "Spec")
    folder = rule_api.create_project_folder_rule(project_id, r"D:\Client", True)
    assert keyword["ok"] is True
    assert folder["ok"] is True
