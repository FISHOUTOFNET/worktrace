"""Keyword-rule edit API and generation contracts."""

from __future__ import annotations

import json

import pytest

from worktrace.services import system_project_service

from worktrace.api import rule_api
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


def _row(rule_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, rule_type, pattern, enabled,
                   created_by, created_at, updated_at
            FROM project_rule
            WHERE id = ?
            """,
            (rule_id,),
        ).fetchone()
    return dict(row) if row else None


def test_update_keyword_rule_trims_and_preserves_identity(temp_db):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)
    rule_service.set_rule_enabled(rule_id, False)
    before = _row(rule_id)

    result = rule_api.update_project_keyword_rule(rule_id, "  NewSpec  ")

    assert result == {
        "ok": True,
        "rule": {
            "kind": "keyword",
            "id": rule_id,
            "project_id": project_id,
            "keyword": "NewSpec",
            "enabled": False,
        },
    }
    after = _row(rule_id)
    assert after["project_id"] == project_id
    assert after["pattern"] == "NewSpec"
    assert after["enabled"] == 0
    assert after["created_by"] == before["created_by"]
    assert after["created_at"] == before["created_at"]


@pytest.mark.parametrize(
    ("rule_id", "keyword"),
    [
        (True, "Spec"),
        ("1", "Spec"),
        (1.5, "Spec"),
        (0, "Spec"),
        (-1, "Spec"),
        (None, "Spec"),
        (1, None),
        (1, True),
        (1, 1),
        (1, []),
        (1, ""),
        (1, "   "),
    ],
)
def test_invalid_input_returns_stable_error(temp_db, rule_id, keyword):
    assert rule_api.update_project_keyword_rule(rule_id, keyword) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_unknown_and_folder_rule_ids_return_not_found(temp_db):
    project_id = project_service.create_project("Client")
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )

    assert rule_api.update_project_keyword_rule(9999, "Spec") == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.update_project_keyword_rule(folder_id, "Spec") == {
        "ok": False,
        "error": "not_found",
    }
    assert any(
        int(item["id"]) == folder_id
        for item in folder_rule_service.list_folder_rules()
    )


def test_duplicate_scope_is_per_project_and_own_value_is_allowed(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    rule_service.create_rule("Existing", project_a)
    target_a = rule_service.create_rule("Original", project_a)
    target_b = rule_service.create_rule("Original", project_b)

    assert rule_api.update_project_keyword_rule(target_a, "Existing") == {
        "ok": False,
        "error": "duplicate_rule",
    }
    assert _row(target_a)["pattern"] == "Original"
    assert rule_api.update_project_keyword_rule(target_b, "Existing")["ok"] is True
    assert rule_api.update_project_keyword_rule(target_a, "Original")["ok"] is True


def test_update_refreshes_keyword_cache_via_generation(temp_db):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)
    assert project_inference_service._enabled_keyword_rules()[0]["pattern"] == "spec"
    before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result["ok"] is True
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == before + 1
    assert project_inference_service._enabled_keyword_rules()[0]["pattern"] == "newspec"


def test_excluded_keyword_update_refreshes_privacy_generation(temp_db):
    excluded_id = system_project_service.require_excluded_project_id()
    project_service.set_project_enabled(excluded_id, True)
    rule_id = rule_service.create_rule("Secret", excluded_id)
    assert privacy_service._exclude_rules()["keywords"]
    before = generation(DataGenerationNamespace.PRIVACY_CATALOG)

    result = rule_api.update_project_keyword_rule(rule_id, "Private")

    assert result["ok"] is True
    assert generation(DataGenerationNamespace.PRIVACY_CATALOG) == before + 1
    assert privacy_service._exclude_rules()["keywords"] == [{"keyword": "Private"}]


def test_ordinary_update_does_not_submit_history_job(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)

    def fail_job(*args, **kwargs):
        raise AssertionError("ordinary keyword edit must not submit a history job")

    monkeypatch.setattr(history_mutation_job_service, "submit_rule_job", fail_job)
    assert rule_api.update_project_keyword_rule(rule_id, "NewSpec")["ok"] is True


def test_service_exception_collapses_to_privacy_safe_error(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)

    def boom(*args, **kwargs):
        raise RuntimeError("SELECT traceback window_title clipboard C:\\Secret")

    monkeypatch.setattr(rule_service, "update_rule", boom)
    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result == {"ok": False, "error": "operation_failed"}
    serialized = json.dumps(result).casefold()
    for forbidden in ("select", "traceback", "window_title", "clipboard", "secret"):
        assert forbidden not in serialized


def test_payload_is_json_serializable(temp_db):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)
    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")
    assert json.loads(json.dumps(result))["rule"]["keyword"] == "NewSpec"
