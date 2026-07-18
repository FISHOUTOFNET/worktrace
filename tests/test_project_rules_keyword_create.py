"""Keyword-rule creation API and generation contracts."""

from __future__ import annotations

import json

import pytest

from worktrace.services import system_project_service

from tests.support import activity_factory as activity_service
from tests.support.db_helpers import table_count
from worktrace.api import rule_api
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection
from worktrace.generation_clock import generation
from worktrace.services import (
    history_mutation_job_service,
    project_inference_service,
    project_service,
    rule_service,
)

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.db,
    pytest.mark.security_privacy,
]


def _rule_row(rule_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, pattern, enabled, created_by
            FROM project_rule
            WHERE id = ?
            """,
            (rule_id,),
        ).fetchone()
    return dict(row)


def test_create_keyword_rule_for_normal_project(temp_db):
    project_id = project_service.create_project("Client")

    result = rule_api.create_project_keyword_rule(project_id, "Spec")

    assert result["ok"] is True
    assert result["rule"] == {
        "kind": "keyword",
        "id": result["rule"]["id"],
        "project_id": project_id,
        "keyword": "Spec",
        "enabled": True,
    }
    assert _rule_row(result["rule"]["id"]) == {
        "id": result["rule"]["id"],
        "project_id": project_id,
        "pattern": "Spec",
        "enabled": 1,
        "created_by": "user",
    }


@pytest.mark.parametrize("state", ["excluded", "archived", "disabled"])
def test_unavailable_project_is_rejected(temp_db, state):
    if state == "excluded":
        project_id = system_project_service.require_excluded_project_id()
    else:
        project_id = project_service.create_project(state.title())
        if state == "archived":
            project_service.archive_project(project_id)
        else:
            project_service.set_project_enabled(project_id, False)

    assert rule_api.create_project_keyword_rule(project_id, "Spec") == {
        "ok": False,
        "error": "project_not_found",
    }


@pytest.mark.parametrize(
    ("project_id", "keyword"),
    [
        (True, "Spec"),
        ("1", "Spec"),
        (1.5, "Spec"),
        (0, "Spec"),
        (-1, "Spec"),
        (None, "Spec"),
        (1, None),
        (1, True),
        (1, 2.5),
        (1, []),
        (1, ""),
        (1, "   "),
    ],
)
def test_invalid_input_is_rejected(temp_db, project_id, keyword):
    assert rule_api.create_project_keyword_rule(project_id, keyword) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_keyword_is_trimmed_and_duplicate_scope_is_per_project(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")

    first = rule_api.create_project_keyword_rule(project_a, "  Spec  ")
    assert first["ok"] is True
    assert first["rule"]["keyword"] == "Spec"
    assert rule_api.create_project_keyword_rule(project_a, "Spec") == {
        "ok": False,
        "error": "duplicate_rule",
    }
    assert rule_api.create_project_keyword_rule(project_a, "spec")["ok"] is True
    assert rule_api.create_project_keyword_rule(project_b, "Spec")["ok"] is True


def test_plain_text_keyword_is_json_serializable(temp_db):
    project_id = project_service.create_project("Client")
    keyword = "<script>alert('xss')</script>"

    result = rule_api.create_project_keyword_rule(project_id, keyword)

    assert result["ok"] is True
    assert result["rule"]["keyword"] == keyword
    assert json.loads(json.dumps(result, ensure_ascii=False))["ok"] is True


def test_creation_does_not_mutate_history_or_submit_job(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
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

    def fail_job(*args, **kwargs):
        raise AssertionError("rule creation must not submit a history job")

    monkeypatch.setattr(history_mutation_job_service, "submit_rule_job", fail_job)
    result = rule_api.create_project_keyword_rule(project_id, "Spec")

    assert result["ok"] is True
    assert table_count("project_rule") == 1
    assert {
        "project": table_count("project"),
        "folder": table_count("folder_project_rule"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "operation": table_count("report_session_operation"),
    } == before


def test_creation_refreshes_keyword_cache_via_generation(temp_db):
    project_id = project_service.create_project("Client")
    assert project_inference_service._enabled_keyword_rules() == []
    before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    result = rule_api.create_project_keyword_rule(project_id, "Spec")

    assert result["ok"] is True
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == before + 1
    assert project_inference_service._enabled_keyword_rules() == [
        {
            "id": result["rule"]["id"],
            "project_id": project_id,
            "pattern": "spec",
        }
    ]


def test_service_exception_collapses_to_privacy_safe_error(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")

    def boom(*args, **kwargs):
        raise RuntimeError("SELECT traceback window_title clipboard C:\\Secret")

    monkeypatch.setattr(rule_service, "create_rule", boom)
    result = rule_api.create_project_keyword_rule(project_id, "Spec")

    assert result == {"ok": False, "error": "operation_failed"}
    serialized = json.dumps(result).casefold()
    for forbidden in ("select", "traceback", "window_title", "clipboard", "secret"):
        assert forbidden not in serialized
