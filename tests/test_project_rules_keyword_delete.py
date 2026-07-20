"""Keyword-rule deletion API and generation contracts."""

from __future__ import annotations

import json

import pytest

from tests.support import activity_factory as activity_service
from tests.support.db_helpers import table_count
from worktrace.api import rule_api
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection
from worktrace.generation_clock import generation
from worktrace.services import (
    folder_rule_service,
    privacy_service,
    project_inference_service,
    project_service,
    rule_catalog_command_service,
    rule_history_application_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _exists(rule_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS value FROM project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
    return int(row["value"] or 0) == 1


def test_delete_enabled_and_disabled_keyword_rules(temp_db):
    project_id = project_service.create_project("Client")
    enabled_id = rule_service.create_rule("Enabled", project_id)
    disabled_id = rule_service.create_rule("Disabled", project_id)
    rule_service.set_rule_enabled(disabled_id, False)

    for rule_id in (enabled_id, disabled_id):
        result = rule_api.delete_project_keyword_rule(
            rule_id,
            apply_to_history=False,
        )
        assert result == {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "deleted": True,
                "history_updated": False,
                "updated_count": 0,
            },
        }
        assert not _exists(rule_id)


def test_delete_keyword_rule_under_excluded_project(temp_db):
    rule_id, excluded_id = rule_catalog_command_service.create_excluded_keyword_rule(
        "Secret"
    )
    assert excluded_id > 0

    before = generation(DataGenerationNamespace.PRIVACY_CATALOG)
    result = rule_api.delete_project_keyword_rule(
        rule_id,
        apply_to_history=False,
    )

    assert result["ok"] is True
    assert not _exists(rule_id)
    assert generation(DataGenerationNamespace.PRIVACY_CATALOG) == before + 1
    assert privacy_service._exclude_rules()["keywords"] == []


@pytest.mark.parametrize("bad_id", [True, False, "1", 1.5, 0, -1, None, [], {}])
def test_invalid_rule_id_returns_invalid_input(temp_db, bad_id):
    assert rule_api.delete_project_keyword_rule(
        bad_id,
        apply_to_history=False,
    ) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_unknown_and_cross_type_ids_return_not_found(temp_db):
    project_id = project_service.create_project("Client")
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )

    assert rule_api.delete_project_keyword_rule(
        9999,
        apply_to_history=False,
    ) == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.delete_project_keyword_rule(
        folder_id,
        apply_to_history=False,
    ) == {
        "ok": False,
        "error": "not_found",
    }
    assert any(
        int(row["id"]) == folder_id
        for row in folder_rule_service.list_folder_rules()
    )


def test_delete_preserves_projects_folder_rules_and_history(temp_db):
    project_id = project_service.create_project("Client")
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )
    rule_id = rule_service.create_rule("Spec", project_id)
    activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project_id,
    )
    before = {
        "project": table_count("project"),
        "folder": table_count("folder_project_rule"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "operation": table_count("report_session_operation"),
    }

    result = rule_api.delete_project_keyword_rule(
        rule_id,
        apply_to_history=False,
    )

    assert result["ok"] is True
    assert {
        "project": table_count("project"),
        "folder": table_count("folder_project_rule"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "operation": table_count("report_session_operation"),
    } == before
    assert any(
        int(row["id"]) == folder_id
        for row in folder_rule_service.list_folder_rules()
    )


def test_delete_refreshes_keyword_cache_via_generation(temp_db):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)
    assert project_inference_service._enabled_keyword_rules()
    before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    result = rule_api.delete_project_keyword_rule(
        rule_id,
        apply_to_history=False,
    )

    assert result["ok"] is True
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == before + 1
    assert project_inference_service._enabled_keyword_rules() == []


def test_explicit_history_choice_returns_job_metadata(temp_db):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)

    result = rule_api.delete_project_keyword_rule(rule_id, apply_to_history=True)

    assert result["ok"] is True
    assert result["rule"]["history_updated"] is True
    assert result["rule"]["updated_count"] >= 0
    assert not _exists(rule_id)


def test_service_exception_collapses_to_privacy_safe_error(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)

    def boom(*args, **kwargs):
        raise RuntimeError("SELECT traceback window_title clipboard C:\\Secret")

    monkeypatch.setattr(rule_history_application_service, "delete_rule", boom)
    result = rule_api.delete_project_keyword_rule(
        rule_id,
        apply_to_history=False,
    )

    assert result == {"ok": False, "error": "operation_failed"}
    serialized = json.dumps(result).casefold()
    for forbidden in ("select", "traceback", "window_title", "clipboard", "secret"):
        assert forbidden not in serialized
