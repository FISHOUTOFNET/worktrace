from __future__ import annotations

import pytest

from worktrace.api import rule_api
from worktrace.constants import EXCLUDED_PROJECT
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_inference_service,
    project_service,
    rule_service,
)


def _counts() -> dict[str, int]:
    with get_connection() as conn:
        return {
            "project": conn.execute("SELECT COUNT(*) AS c FROM project").fetchone()["c"],
            "folder": conn.execute("SELECT COUNT(*) AS c FROM folder_project_rule").fetchone()["c"],
            "keyword": conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"],
            "activity": conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"],
            "assignment": conn.execute(
                "SELECT COUNT(*) AS c FROM activity_project_assignment"
            ).fetchone()["c"],
            "session_note": conn.execute(
                "SELECT COUNT(*) AS c FROM project_session_note"
            ).fetchone()["c"],
        }


def _enabled(table: str, rule_id: int) -> int:
    with get_connection() as conn:
        return int(
            conn.execute(f"SELECT enabled FROM {table} WHERE id = ?", (rule_id,)).fetchone()[
                "enabled"
            ]
        )


def test_keyword_rule_disable_enable_updates_existing_row(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    disabled = rule_api.set_project_rule_enabled("keyword", rule_id, False)

    assert disabled == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": rule_id,
        "enabled": False,
    }
    assert _enabled("project_rule", rule_id) == 0
    enabled = rule_api.set_project_rule_enabled("keyword", rule_id, True)
    assert enabled == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": rule_id,
        "enabled": True,
    }
    assert _enabled("project_rule", rule_id) == 1


def test_folder_rule_disable_enable_updates_existing_row(temp_db):
    project = project_service.create_project("Client")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    disabled = rule_api.set_project_rule_enabled("folder", rule_id, False)

    assert disabled == {
        "ok": True,
        "rule_type": "folder",
        "rule_id": rule_id,
        "enabled": False,
    }
    assert _enabled("folder_project_rule", rule_id) == 0
    enabled = rule_api.set_project_rule_enabled("folder", rule_id, True)
    assert enabled == {
        "ok": True,
        "rule_type": "folder",
        "rule_id": rule_id,
        "enabled": True,
    }
    assert _enabled("folder_project_rule", rule_id) == 1


def test_missing_rules_return_stable_not_found(temp_db):
    assert rule_api.set_project_rule_enabled("keyword", 999, False) == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.set_project_rule_enabled("folder", 999, False) == {
        "ok": False,
        "error": "not_found",
    }


def test_invalid_rule_type_returns_stable_invalid_input(temp_db):
    assert rule_api.set_project_rule_enabled("project", 1, True) == {
        "ok": False,
        "error": "invalid_input",
    }


@pytest.mark.parametrize("bad_id", [None, True, False, "1", 0, -1, 1.0])
def test_invalid_rule_id_returns_stable_invalid_input(temp_db, bad_id):
    assert rule_api.set_project_rule_enabled("keyword", bad_id, True) == {
        "ok": False,
        "error": "invalid_input",
    }


@pytest.mark.parametrize("bad_enabled", [None, 0, 1, "true", "false"])
def test_invalid_enabled_returns_stable_invalid_input(temp_db, bad_enabled):
    assert rule_api.set_project_rule_enabled("keyword", 1, bad_enabled) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_toggle_does_not_create_or_delete_projects_rules_or_activity_rows(temp_db):
    project = project_service.create_project("Client")
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)
    keyword_rule = rule_service.create_rule("Spec", project)
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project,
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO project_session_note(report_date, first_activity_id, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-06-18", activity_id, "keep", now_str(), now_str()),
        )
    before = _counts()

    assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True

    assert _counts() == before


def test_folder_toggle_does_not_trigger_backfill(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    def fail_backfill(*args, **kwargs):
        raise AssertionError("backfill must not run")

    monkeypatch.setattr(folder_rule_service, "backfill_folder_rule", fail_backfill)

    assert rule_api.set_project_rule_enabled("folder", rule_id, False)["ok"] is True


def test_toggles_invalidate_relevant_caches(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    keyword_rule = rule_service.create_rule("Spec", project)
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)
    project_inference_service.invalidate_keyword_rule_cache()
    folder_rule_service.invalidate_folder_rule_cache()
    assert project_inference_service._enabled_keyword_rules()
    assert folder_rule_service.find_matching_folder_rule("D:\\Client\\Spec.docx")

    keyword_calls = {"count": 0}
    folder_calls = {"count": 0}

    def keyword_invalidate():
        keyword_calls["count"] += 1
        project_inference_service.invalidate_keyword_rule_cache()

    def folder_invalidate():
        folder_calls["count"] += 1
        folder_rule_service._FOLDER_RULE_CACHE.clear()

    monkeypatch.setattr(rule_service, "invalidate_keyword_rule_cache", keyword_invalidate)
    monkeypatch.setattr(folder_rule_service, "invalidate_folder_rule_cache", folder_invalidate)

    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
    assert keyword_calls["count"] == 1
    assert folder_calls["count"] == 1


def test_excluded_project_existing_rules_can_be_toggled(temp_db):
    excluded_project = project_service.get_or_create_excluded_project()
    keyword_rule = rule_service.create_rule("Secret", excluded_project)
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Secret", excluded_project)

    bindings = project_service.list_project_bindings()
    excluded = next(project for project in bindings if project["name"] == EXCLUDED_PROJECT)
    assert excluded["enabled"] == 0

    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
    assert _enabled("project_rule", keyword_rule) == 0
    assert _enabled("folder_project_rule", folder_rule) == 0
