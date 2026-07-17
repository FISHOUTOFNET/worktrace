"""Folder-rule CRUD, generation, and isolation contracts."""

from __future__ import annotations

import json

import pytest

from tests.support.db_helpers import table_count
from worktrace.api import rule_api
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection
from worktrace.generation_clock import generation
from worktrace.path_utils import normalize_folder_key
from worktrace.services import (
    folder_index_service,
    folder_rule_service,
    history_mutation_job_service,
    project_service,
    rule_history_application_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _folder_rule(rule_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, folder_path, normalized_folder_key,
                   recursive, enabled
            FROM folder_project_rule
            WHERE id = ?
            """,
            (rule_id,),
        ).fetchone()
    return dict(row) if row else None


def _keyword_exists(rule_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS value FROM project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
    return int(row["value"] or 0) == 1


def test_create_folder_rule_and_index_request(temp_db):
    project_id = project_service.create_project("Client")
    before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    result = rule_api.create_project_folder_rule(
        project_id,
        r"D:\Work\Client",
        True,
    )

    assert result["ok"] is True
    rule_id = result["rule"]["id"]
    assert result["rule"] == {
        "kind": "folder",
        "id": rule_id,
        "project_id": project_id,
        "folder_path": r"D:\Work\Client",
        "recursive": True,
        "enabled": True,
    }
    row = _folder_rule(rule_id)
    assert row["normalized_folder_key"] == normalize_folder_key(r"D:\Work\Client")
    assert row["recursive"] == 1
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == before + 1
    with get_connection() as conn:
        state = conn.execute(
            "SELECT refresh_requested FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (rule_id,),
        ).fetchone()
    assert int(state["refresh_requested"] or 0) == 1


def test_create_same_normalized_path_updates_existing_row(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    first = rule_api.create_project_folder_rule(project_a, r"D:\Work", True)

    second = rule_api.create_project_folder_rule(project_b, r"D:\Work", False)

    assert second["ok"] is True
    assert second["rule"]["id"] == first["rule"]["id"]
    row = _folder_rule(first["rule"]["id"])
    assert row["project_id"] == project_b
    assert row["recursive"] == 0
    assert row["enabled"] == 1


@pytest.mark.parametrize("state", ["excluded", "archived", "disabled"])
def test_create_rejects_unavailable_project(temp_db, state):
    if state == "excluded":
        project_id = project_service.get_or_create_excluded_project()
    else:
        project_id = project_service.create_project(state.title())
        if state == "archived":
            project_service.archive_project(project_id)
        else:
            project_service.set_project_enabled(project_id, False)

    assert rule_api.create_project_folder_rule(project_id, r"D:\Work", True) == {
        "ok": False,
        "error": "project_not_found",
    }


@pytest.mark.parametrize(
    ("project_id", "path", "recursive"),
    [
        (True, r"D:\Work", True),
        ("1", r"D:\Work", True),
        (0, r"D:\Work", True),
        (None, r"D:\Work", True),
        (1, None, True),
        (1, [], True),
        (1, "", True),
        (1, "   ", True),
        (1, r"D:\Work", 1),
        (1, r"D:\Work", "true"),
    ],
)
def test_create_rejects_invalid_inputs(temp_db, project_id, path, recursive):
    assert rule_api.create_project_folder_rule(project_id, path, recursive) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_update_preserves_id_project_and_disabled_state(temp_db):
    project_id = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project_id, r"D:\Old", True)
    rule_id = created["rule"]["id"]
    folder_rule_service.set_folder_rule_enabled(rule_id, False)

    result = rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    assert result["ok"] is True
    assert result["rule"]["id"] == rule_id
    row = _folder_rule(rule_id)
    assert row["project_id"] == project_id
    assert row["folder_path"] == r"D:\New"
    assert row["recursive"] == 0
    assert row["enabled"] == 0


def test_update_normalized_key_conflict_rolls_back(temp_db):
    project_id = project_service.create_project("Client")
    other = rule_api.create_project_folder_rule(project_id, r"D:\Other", True)
    target = rule_api.create_project_folder_rule(project_id, r"D:\Target", True)

    result = rule_api.update_project_folder_rule(
        target["rule"]["id"],
        r"D:\Other",
        True,
    )

    assert result == {"ok": False, "error": "operation_failed"}
    assert _folder_rule(other["rule"]["id"])["folder_path"] == r"D:\Other"
    assert _folder_rule(target["rule"]["id"])["folder_path"] == r"D:\Target"


def test_delete_folder_rule_isolated_from_keyword_rules_and_history(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project_id)
    folder = rule_api.create_project_folder_rule(project_id, r"D:\Work", True)
    before = {
        "project": table_count("project"),
        "keyword": table_count("project_rule"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "operation": table_count("report_session_operation"),
    }

    result = rule_api.delete_project_folder_rule(folder["rule"]["id"])

    assert result["ok"] is True
    assert _folder_rule(folder["rule"]["id"]) is None
    assert _keyword_exists(keyword_id)
    assert {
        "project": table_count("project"),
        "keyword": table_count("project_rule"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "operation": table_count("report_session_operation"),
    } == before


def test_delete_rejects_keyword_id_and_invalid_id(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project_id)

    assert rule_api.delete_project_folder_rule(keyword_id) == {
        "ok": False,
        "error": "not_found",
    }
    assert _keyword_exists(keyword_id)
    for bad_id in (True, "1", 0, -1, 1.5, None, [], {}):
        assert rule_api.delete_project_folder_rule(bad_id) == {
            "ok": False,
            "error": "invalid_input",
        }


def test_ordinary_crud_does_not_submit_history_job(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")

    def fail_job(*args, **kwargs):
        raise AssertionError("ordinary folder CRUD must not submit a history job")

    monkeypatch.setattr(history_mutation_job_service, "submit_rule_job", fail_job)
    created = rule_api.create_project_folder_rule(project_id, r"D:\Work", True)
    assert created["ok"] is True
    assert rule_api.update_project_folder_rule(
        created["rule"]["id"],
        r"D:\New",
        False,
    )["ok"] is True
    assert rule_api.delete_project_folder_rule(created["rule"]["id"])["ok"] is True


def test_explicit_history_delete_returns_job_metadata(temp_db):
    project_id = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project_id, r"D:\Work", True)

    result = rule_api.delete_project_folder_rule(
        created["rule"]["id"],
        apply_to_history=True,
    )

    assert result["ok"] is True
    assert result["rule"]["history_updated"] is True
    assert _folder_rule(created["rule"]["id"]) is None


def test_service_exceptions_are_privacy_safe(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project_id, r"D:\Work", True)

    def boom(*args, **kwargs):
        raise RuntimeError("DELETE SELECT traceback C:\\Secret")

    monkeypatch.setattr(rule_history_application_service, "delete_rule", boom)
    result = rule_api.delete_project_folder_rule(created["rule"]["id"])

    assert result == {"ok": False, "error": "operation_failed"}
    serialized = json.dumps(result).casefold()
    for forbidden in ("delete", "select", "traceback", "secret"):
        assert forbidden not in serialized
