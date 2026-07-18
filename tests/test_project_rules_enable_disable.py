from __future__ import annotations

import json

import pytest

from worktrace.services import system_project_service

from tests.support import activity_factory as activity_service
from worktrace.api import rule_api
from worktrace.constants import EXCLUDED_PROJECT
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


def _enabled(table: str, rule_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT enabled FROM {table} WHERE id = ?",
            (rule_id,),
        ).fetchone()
    return int(row["enabled"])


def _history_counts() -> tuple[int, int, int]:
    with get_connection() as conn:
        return (
            int(conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"]),
            int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM activity_project_assignment"
                ).fetchone()["c"]
            ),
            int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM report_session_operation"
                ).fetchone()["c"]
            ),
        )


def test_keyword_rule_disable_enable_updates_existing_row(temp_db):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project_id)

    assert rule_api.set_project_rule_enabled("keyword", rule_id, False) == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": rule_id,
        "enabled": False,
    }
    assert _enabled("project_rule", rule_id) == 0
    assert rule_api.set_project_rule_enabled("keyword", rule_id, True)["ok"] is True
    assert _enabled("project_rule", rule_id) == 1


def test_folder_rule_disable_enable_updates_existing_row(temp_db):
    project_id = project_service.create_project("Client")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )

    assert rule_api.set_project_rule_enabled("folder", rule_id, False)["ok"] is True
    assert _enabled("folder_project_rule", rule_id) == 0
    assert rule_api.set_project_rule_enabled("folder", rule_id, True)["ok"] is True
    assert _enabled("folder_project_rule", rule_id) == 1


@pytest.mark.parametrize(
    ("rule_type", "rule_id", "enabled"),
    [
        ("project", 1, True),
        (None, 1, True),
        ([], 1, True),
        ("keyword", 0, True),
        ("keyword", True, True),
        ("folder", "1", True),
        ("keyword", 1, 1),
        ("folder", 1, "false"),
    ],
)
def test_invalid_toggle_inputs_return_stable_error(
    temp_db,
    rule_type,
    rule_id,
    enabled,
):
    assert rule_api.set_project_rule_enabled(rule_type, rule_id, enabled) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_missing_rules_return_not_found_without_calling_writer(temp_db, monkeypatch):
    calls = {"keyword": 0, "folder": 0}

    def fail_keyword(*args, **kwargs):
        calls["keyword"] += 1
        raise AssertionError("missing keyword rule must not reach writer")

    def fail_folder(*args, **kwargs):
        calls["folder"] += 1
        raise AssertionError("missing folder rule must not reach writer")

    monkeypatch.setattr(rule_service, "set_rule_enabled", fail_keyword)
    monkeypatch.setattr(folder_rule_service, "set_folder_rule_enabled", fail_folder)

    assert rule_api.set_project_rule_enabled("keyword", 999, False) == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.set_project_rule_enabled("folder", 999, False) == {
        "ok": False,
        "error": "not_found",
    }
    assert calls == {"keyword": 0, "folder": 0}


def test_toggle_does_not_submit_history_job_or_change_history(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )
    activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project_id,
    )
    before = _history_counts()

    def fail_job(*args, **kwargs):
        raise AssertionError("ordinary toggle must not submit a history job")

    monkeypatch.setattr(history_mutation_job_service, "submit_rule_job", fail_job)

    assert rule_api.set_project_rule_enabled("keyword", keyword_id, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("folder", folder_id, False)["ok"] is True
    assert _history_counts() == before


def test_toggle_invalidates_rule_caches_via_catalog_generation(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )
    assert project_inference_service._enabled_keyword_rules()
    assert folder_rule_service.find_matching_folder_rule(r"D:\Client\Spec.docx")
    before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    assert rule_api.set_project_rule_enabled("keyword", keyword_id, False)["ok"] is True
    after_keyword = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    assert after_keyword == before + 1
    assert project_inference_service._enabled_keyword_rules() == []

    assert rule_api.set_project_rule_enabled("folder", folder_id, False)["ok"] is True
    after_folder = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    assert after_folder == after_keyword + 1
    assert folder_rule_service.find_matching_folder_rule(r"D:\Client\Spec.docx") is None


def test_excluded_rule_toggle_invalidates_privacy_generation(temp_db):
    excluded_id = system_project_service.require_excluded_project_id()
    project_service.set_project_enabled(excluded_id, True)
    keyword_id = rule_service.create_rule("Secret", excluded_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Secret",
        excluded_id,
    )
    assert privacy_service._exclude_rules()
    before = generation(DataGenerationNamespace.PRIVACY_CATALOG)

    assert rule_api.set_project_rule_enabled("keyword", keyword_id, False)["ok"] is True
    after_keyword = generation(DataGenerationNamespace.PRIVACY_CATALOG)
    assert after_keyword == before + 1

    assert rule_api.set_project_rule_enabled("folder", folder_id, False)["ok"] is True
    assert generation(DataGenerationNamespace.PRIVACY_CATALOG) == after_keyword + 1
    excluded = next(
        item
        for item in project_service.list_project_bindings()
        if item["name"] == EXCLUDED_PROJECT
    )
    assert excluded["enabled"] == 1


def test_idempotent_toggle_does_not_bump_catalog_generation(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project_id)
    before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    assert rule_api.set_project_rule_enabled("keyword", keyword_id, True)["ok"] is True
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == before


def test_service_exceptions_are_folded_to_operation_failed(temp_db, monkeypatch):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )

    def boom(*args, **kwargs):
        raise RuntimeError("SELECT traceback window_title clipboard C:\\Secret")

    monkeypatch.setattr(rule_service, "set_rule_enabled", boom)
    keyword_result = rule_api.set_project_rule_enabled("keyword", keyword_id, False)
    monkeypatch.setattr(folder_rule_service, "set_folder_rule_enabled", boom)
    folder_result = rule_api.set_project_rule_enabled("folder", folder_id, False)

    assert keyword_result == {"ok": False, "error": "operation_failed"}
    assert folder_result == {"ok": False, "error": "operation_failed"}
    serialized = json.dumps([keyword_result, folder_result]).casefold()
    for forbidden in ("select", "traceback", "window_title", "clipboard", "secret"):
        assert forbidden not in serialized


def test_toggle_payload_is_json_serializable_and_stable(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project_id)
    result = rule_api.set_project_rule_enabled("keyword", keyword_id, False)
    assert json.loads(json.dumps(result)) == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": keyword_id,
        "enabled": False,
    }
