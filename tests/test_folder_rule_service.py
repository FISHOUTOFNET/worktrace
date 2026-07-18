from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from tests.support.db_helpers import assign_activity_project
from worktrace.api import rule_history_api as rule_api
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.db import get_connection, now_str
from worktrace.generation_clock import generation
from worktrace.services import (
    folder_rule_service,
    project_service,
    rule_service,
)
from worktrace.services.project_inference_service import assign_project_for_activity

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _activity_with_path(path: str, title: str = "Spec.docx - Word") -> int:
    return activity_service.create_activity(
        "Word",
        "winword.exe",
        title,
        file_path_hint=path,
        start_time="2026-06-18 09:00:00",
    )


def _close_directly(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET end_time = ?, duration_seconds = ?, updated_at = ?
            WHERE id = ?
            """,
            ("2026-06-18 09:10:00", 600, now_str(), activity_id),
        )


def test_longest_child_folder_rule_wins(temp_db):
    parent_project = project_service.create_project("Parent")
    child_project = project_service.create_project("Child")
    folder_rule_service.create_or_update_folder_rule(r"D:\CaseA", parent_project)
    folder_rule_service.create_or_update_folder_rule(
        r"D:\CaseA\Sub",
        child_project,
    )

    rule = folder_rule_service.find_matching_folder_rule(
        r"D:\CaseA\Sub\Spec.docx"
    )

    assert rule["project_id"] == child_project


def test_folder_rule_cache_reloads_after_catalog_generation(temp_db, monkeypatch):
    parent_project = project_service.create_project("Parent")
    folder_rule_service.create_or_update_folder_rule(r"D:\CaseA", parent_project)
    original = folder_rule_service.get_connection
    calls = {"count": 0}

    def counted_connection():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(folder_rule_service, "get_connection", counted_connection)
    assert folder_rule_service.find_matching_folder_rule(
        r"D:\CaseA\Spec.docx"
    )["project_id"] == parent_project
    assert folder_rule_service.find_matching_folder_rule(
        r"D:\CaseA\Other.docx"
    )["project_id"] == parent_project
    assert calls["count"] == 1

    before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    child_project = project_service.create_project("Child")
    folder_rule_service.create_or_update_folder_rule(
        r"D:\CaseA\Sub",
        child_project,
    )
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == before + 2
    assert folder_rule_service.find_matching_folder_rule(
        r"D:\CaseA\Sub\Spec.docx"
    )["project_id"] == child_project
    assert calls["count"] == 2


def test_folder_rule_wins_over_keyword_and_persists_source(temp_db):
    folder_project = project_service.create_project("Folder")
    keyword_project = project_service.create_project("Keyword")
    folder_rule_service.create_or_update_folder_rule(r"D:\CaseA", folder_project)
    rule_service.create_rule("Spec", keyword_project)
    activity_id = _activity_with_path(r"D:\CaseA\Spec.docx")

    assign_project_for_activity(activity_id)

    row = activity_service.get_activity(activity_id)
    assert row["project_id"] == folder_project
    assert row["assignment_source"] == "folder_rule"


def test_durable_backfill_preserves_manual_override(temp_db):
    folder_project = project_service.create_project("Folder")
    manual_project = project_service.create_project("Manual")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\CaseA",
        folder_project,
    )
    activity_id = _activity_with_path(
        r"D:\CaseA\Manual.docx",
        "Manual.docx - Word",
    )
    assign_activity_project(activity_id, manual_project, manual=True)
    _close_directly(activity_id)

    result = rule_api.backfill_project_rule("folder", rule_id)

    assert result["ok"] is True
    assert result["result"]["updated_count"] == 0
    assert activity_service.get_activity(activity_id)["project_id"] == manual_project


def test_durable_backfill_updates_eligible_activity(temp_db):
    folder_project = project_service.create_project("Folder")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\CaseA",
        folder_project,
    )
    activity_id = _activity_with_path(
        r"D:\CaseA\Eligible.docx",
        "Eligible.docx - Word",
    )
    _close_directly(activity_id)

    result = rule_api.backfill_project_rule("folder", rule_id)

    assert result["ok"] is True
    assert result["result"]["updated_count"] == 1
    assert activity_service.get_activity(activity_id)["project_id"] == folder_project


def test_preview_folder_rule_conflicts_counts_folder_scope(temp_db):
    parent_project = project_service.create_project("Parent")
    child_project = project_service.create_project("Child")
    folder_rule_service.create_or_update_folder_rule(
        r"D:\CaseA\Sub",
        child_project,
    )
    activity_id = _activity_with_path(
        r"D:\CaseA\Manual.docx",
        "Manual.docx - Word",
    )
    assign_activity_project(activity_id, child_project, manual=True)

    preview = folder_rule_service.preview_folder_rule_conflicts(
        r"D:\CaseA",
        parent_project,
    )

    assert preview["child_folder_rule_conflicts"] == 1
    assert preview["other_project_activity_count"] == 1
    assert preview["manual_activity_count"] == 1
