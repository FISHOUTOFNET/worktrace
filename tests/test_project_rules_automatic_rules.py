"""Automatic Project Rules contracts through the durable inference boundary."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.support import activity_factory as activity_service
from tests.support.db_helpers import assign_activity_project
from worktrace.api import rule_history_api as rule_api
from worktrace.db import get_connection
from worktrace.services import (
    activity_inference_job_repository,
    activity_inference_job_service,
    activity_lifecycle_service,
    folder_rule_service,
    project_inference_service,
    project_service,
    rule_automation_service,
    rule_service,
    system_project_service,
)
from worktrace.webview_ui.bridge_rules import ProjectRulesBridgeMixin

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _create_closed_activity(
    *,
    app_name: str = "Word",
    process_name: str = "winword.exe",
    window_title: str = "Doc.docx - Word",
    start_time: str = "2026-06-25 09:00:00",
    end_time: str = "2026-06-25 09:10:00",
    file_path_hint: str | None = None,
    status: str = "normal",
    project_id: int | None = None,
) -> int:
    activity_id = activity_service.create_activity(
        app_name,
        process_name,
        window_title,
        status=status,
        start_time=start_time,
        file_path_hint=file_path_hint,
        project_id=project_id,
    )
    activity_service.close_activity(activity_id, end_time)
    return activity_id


def _consume(activity_id: int) -> int:
    with get_connection() as conn:
        activity_inference_job_repository.enqueue_closed_activity_ids(
            conn,
            [int(activity_id)],
        )
    return activity_inference_job_service.process_pending_inference_jobs(
        project_inference_service.assign_project_for_activity_in_transaction,
        limit=1,
        activity_ids=[int(activity_id)],
    )


def _assignment(activity_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
            (int(activity_id),),
        ).fetchone()
    return dict(row) if row else {}


def _job(activity_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_inference_job WHERE activity_id = ?",
            (int(activity_id),),
        ).fetchone()
    return dict(row) if row else None


def test_rule_confidence_and_priority_contracts(temp_db):
    assert rule_automation_service.FOLDER_RULE_CONFIDENCE == 85
    assert rule_automation_service.KEYWORD_RULE_CONFIDENCE == 80
    assert rule_automation_service.FOLDER_RULE_SOURCE == "folder_rule"
    assert rule_automation_service.KEYWORD_RULE_SOURCE == "keyword_rule"
    assert rule_automation_service.AUTOMATIC_RULE_PRIORITY == (
        "folder_rule",
        "keyword_rule",
    )


def test_enabled_folder_rule_applies_when_durable_job_is_consumed(temp_db):
    project_id = project_service.create_project("FolderAuto")
    folder_rule_service.create_or_update_folder_rule("D:\\AutoFolder", project_id)
    activity_id = _create_closed_activity(
        file_path_hint="D:\\AutoFolder\\Doc.docx"
    )

    assert _consume(activity_id) == 1

    assignment = _assignment(activity_id)
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "folder_rule"
    assert int(assignment["confidence"]) == 85
    assert int(assignment["is_manual"]) == 0
    assert _job(activity_id) is None


def test_enabled_keyword_rule_applies_when_durable_job_is_consumed(temp_db):
    project_id = project_service.create_project("KeywordAuto")
    rule_service.create_rule("invoice", project_id)
    activity_id = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="invoice-2026.xlsx - Excel",
    )

    assert _consume(activity_id) == 1

    assignment = _assignment(activity_id)
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "keyword_rule"
    assert int(assignment["confidence"]) == 80


def test_disabled_rules_and_projects_do_not_apply(temp_db):
    folder_project = project_service.create_project("DisabledFolderProject")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        "D:\\DisabledFolder",
        folder_project,
    )
    folder_rule_service.set_folder_rule_enabled(folder_rule_id, False)
    folder_activity = _create_closed_activity(
        file_path_hint="D:\\DisabledFolder\\Doc.docx"
    )
    _consume(folder_activity)
    assert _assignment(folder_activity).get("project_id") != folder_project

    keyword_project = project_service.create_project("DisabledKeywordProject")
    keyword_rule_id = rule_service.create_rule("secretkeyword", keyword_project)
    rule_service.set_rule_enabled(keyword_rule_id, False)
    keyword_activity = _create_closed_activity(
        window_title="secretkeyword-report.xlsx - Excel"
    )
    _consume(keyword_activity)
    assert _assignment(keyword_activity).get("project_id") != keyword_project

    archived_project = project_service.create_project("ArchivedProject")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\ArchivedFolder",
        archived_project,
    )
    project_service.archive_project(archived_project)
    archived_activity = _create_closed_activity(
        file_path_hint="D:\\ArchivedFolder\\Doc.docx"
    )
    _consume(archived_activity)
    assert _assignment(archived_activity).get("project_id") != archived_project


def test_excluded_system_project_is_not_an_inference_target(temp_db):
    excluded_id = system_project_service.require_excluded_project_id()
    folder_rule_service.create_or_update_folder_rule(
        "D:\\ExcludedFolder",
        excluded_id,
    )
    activity_id = _create_closed_activity(
        file_path_hint="D:\\ExcludedFolder\\Doc.docx"
    )
    _consume(activity_id)
    assert _assignment(activity_id).get("project_id") != excluded_id


def test_manual_assignment_is_never_overwritten_or_enqueued(temp_db):
    automatic_project = project_service.create_project("Automatic")
    manual_project = project_service.create_project("Manual")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\ManualFolder",
        automatic_project,
    )
    activity_id = _create_closed_activity(
        file_path_hint="D:\\ManualFolder\\Doc.docx"
    )
    assign_activity_project(activity_id, manual_project, manual=True)

    with get_connection() as conn:
        inserted = activity_inference_job_repository.enqueue_closed_activity_ids(
            conn,
            [activity_id],
        )
    assert inserted == 0
    assignment = _assignment(activity_id)
    assert int(assignment["project_id"]) == manual_project
    assert int(assignment["is_manual"]) == 1


def test_open_hidden_deleted_and_non_normal_rows_are_not_enqueued(temp_db):
    project_id = project_service.create_project("Eligibility")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\Eligibility",
        project_id,
    )
    hidden_id = _create_closed_activity(
        file_path_hint="D:\\Eligibility\\hidden.docx"
    )
    deleted_id = _create_closed_activity(
        file_path_hint="D:\\Eligibility\\deleted.docx"
    )
    idle_id = _create_closed_activity(
        file_path_hint="D:\\Eligibility\\idle.docx",
        status="idle",
    )
    open_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Open",
        file_path_hint="D:\\Eligibility\\open.docx",
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (hidden_id,),
        )
        conn.execute(
            "UPDATE activity_log SET is_deleted = 1 WHERE id = ?",
            (deleted_id,),
        )
        inserted = activity_inference_job_repository.enqueue_closed_activity_ids(
            conn,
            [open_id, hidden_id, deleted_id, idle_id],
        )
    assert inserted == 0


def test_folder_rule_wins_over_keyword_rule(temp_db):
    folder_project = project_service.create_project("FolderWins")
    keyword_project = project_service.create_project("KeywordLoses")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\PriorityFolder",
        folder_project,
    )
    rule_service.create_rule("prioritydoc", keyword_project)
    activity_id = _create_closed_activity(
        file_path_hint="D:\\PriorityFolder\\prioritydoc.docx",
        window_title="prioritydoc - Word",
    )
    _consume(activity_id)
    assignment = _assignment(activity_id)
    assert int(assignment["project_id"]) == folder_project
    assert assignment["source"] == "folder_rule"


def test_lifecycle_close_only_enqueues_until_consumer_runs(temp_db):
    project_id = project_service.create_project("CloseTrigger")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\CloseTriggerFolder",
        project_id,
    )
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc.docx - Word",
        file_path_hint="D:\\CloseTriggerFolder\\Doc.docx",
        start_time="2026-06-25 09:00:00",
    )

    activity_lifecycle_service.close_activity(
        activity_id,
        "2026-06-25 09:10:00",
    )

    assert _job(activity_id) is not None
    provisional = _assignment(activity_id)
    assert provisional["source"] == "uncategorized"
    assert int(provisional["is_manual"]) == 0
    assert provisional["source_rule_type"] is None
    assert provisional["source_rule_id"] is None
    assert _consume(activity_id) == 1
    assignment = _assignment(activity_id)
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "folder_rule"


_FORBIDDEN_TOKENS = [
    "window_title",
    "file_path_hint",
    "path_hint",
    "clipboard",
    "traceback",
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "sqlite3",
    "OperationalError",
]
_SQL_KEYWORD_TOKENS = {"SELECT", "INSERT", "UPDATE", "DELETE"}


def _assert_no_sensitive_tokens(payload: dict) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str).lower()
    for token in _FORBIDDEN_TOKENS:
        token_lower = token.lower()
        if token in _SQL_KEYWORD_TOKENS:
            assert re.search(r"\b" + re.escape(token_lower) + r"\b", serialized) is None
        else:
            assert token_lower not in serialized


def test_automatic_rules_status_is_display_safe_and_serializable(temp_db):
    for result in (
        ProjectRulesBridgeMixin().automatic_rules_status(),
        rule_api.automatic_rules_status(),
    ):
        assert result["ok"] is True
        status = result["status"]
        assert status["scope"] == "enabled_folder_keyword_rules"
        assert status["priority"] == "folder_before_keyword"
        assert status["confidence"] == {
            "folder_rule": 85,
            "keyword_rule": 80,
        }
        assert status["writes"]["activity_project_assignment"] is True
        assert status["writes"]["activity_log"] is False
        for field in ("enabled", "toggle", "on", "off", "active", "is_enabled"):
            assert field not in status
        _assert_no_sensitive_tokens(result)
        json.dumps(result, ensure_ascii=False, default=str)


def test_automatic_rule_service_does_not_own_schema_changes(temp_db):
    import inspect

    source = inspect.getsource(rule_automation_service).upper()
    for statement in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE"):
        assert statement not in source
    schema_path = Path(__file__).resolve().parents[1] / "worktrace" / "schema.sql"
    assert schema_path.read_text(encoding="utf-8").strip()
