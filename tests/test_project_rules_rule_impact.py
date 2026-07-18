"""Rule impact preview and durable single-rule history job contracts."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from tests.support import activity_factory as activity_service
from tests.support.db_helpers import assign_activity_project
from worktrace.api import rule_history_api as rule_api
from worktrace.db import get_connection, now_str
from worktrace.services import (
    folder_rule_service,
    project_service,
    rule_impact_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _closed_activity(
    *,
    title: str = "Doc.docx - Word",
    path: str | None = None,
    status: str = "normal",
) -> int:
    start = "2026-06-18 09:00:00"
    end = "2026-06-18 09:10:00"
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        title,
        file_path_hint=path,
        status=status,
        start_time=start,
    )
    duration = int(
        (
            datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            - datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        ).total_seconds()
    )
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET end_time = ?, duration_seconds = ?, updated_at = ?
            WHERE id = ?
            """,
            (end, duration, now_str(), activity_id),
        )
    return activity_id


def _assignment(activity_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT project_id, source, is_manual, source_rule_type,
                   source_rule_id
            FROM activity_project_assignment
            WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
    return dict(row) if row else {}


def test_preview_folder_rule_is_read_only_and_display_safe(temp_db):
    project_id = project_service.create_project("Folder Project")
    activity_id = _closed_activity(
        title=r"C:\Secret\clipboard SELECT",
        path=r"D:\CaseA\Doc.docx",
    )
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\CaseA",
        project_id,
    )

    before = _assignment(activity_id)
    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    after = _assignment(activity_id)

    assert before == after
    assert result["rule"]["kind"] == "folder"
    assert result["rule"]["id"] == rule_id
    assert result["rule"]["enabled"] is True
    assert result["rule"]["project_id"] == project_id
    assert result["rule"]["project_name"] == "Folder Project"
    assert result["rule"]["target"] == r"D:\CaseA"
    assert result["rule"]["project_available"] is True
    assert result["rule"]["version"]
    assert result["counts"]["matched_count"] == 1
    assert result["counts"]["would_update_count"] == 1
    assert result["samples"][0]["activity_id"] == activity_id
    serialized = json.dumps(result, ensure_ascii=False).casefold()
    for secret in ("c:\\secret", "clipboard", "select", "window_title", "path_hint"):
        assert secret not in serialized


def test_preview_keyword_rule_reports_skip_classes(temp_db):
    project_id = project_service.create_project("Keyword Project")
    eligible = _closed_activity(title="invoice.xlsx - Excel")
    manual = _closed_activity(title="invoice manual.xlsx - Excel")
    hidden = _closed_activity(title="invoice hidden.xlsx - Excel")
    _closed_activity(title="invoice idle", status="idle")
    assign_activity_project(manual, project_id, manual=True)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (hidden,),
        )
    rule_id = rule_service.create_rule("invoice", project_id)

    result = rule_impact_service.preview_rule_impact("keyword", rule_id)

    assert result["rule"]["target"] == "invoice"
    assert result["rule"]["version"]
    assert result["counts"]["matched_count"] == 1
    assert result["counts"]["would_update_count"] == 1
    assert result["counts"]["manual_skipped_count"] == 1
    assert result["counts"]["hidden_skipped_count"] == 1
    assert result["counts"]["non_normal_skipped_count"] == 1
    assert result["samples"][0]["activity_id"] == eligible


def test_disabled_rule_preview_is_zero_and_does_not_write(temp_db):
    project_id = project_service.create_project("Disabled")
    activity_id = _closed_activity(title="disabled-token.docx - Word")
    rule_id = rule_service.create_rule("disabled-token", project_id)
    rule_service.set_rule_enabled(rule_id, False)

    result = rule_impact_service.preview_rule_impact("keyword", rule_id)

    assert result["rule"]["enabled"] is False
    assert result["counts"]["would_update_count"] == 0
    assert result["samples"] == []
    assert _assignment(activity_id)["project_id"] != project_id


def test_durable_keyword_backfill_records_exact_rule_origin(temp_db):
    project_id = project_service.create_project("Client")
    activity_id = _closed_activity(title="spec document.docx - Word")
    rule_id = rule_service.create_rule("spec", project_id)

    result = rule_api.backfill_project_rule("keyword", rule_id)

    assert result["ok"] is True
    assert result["result"]["status"] == "completed"
    assert result["result"]["queued"] is False
    assert _assignment(activity_id) == {
        "project_id": project_id,
        "source": "keyword_rule",
        "is_manual": 0,
        "source_rule_type": "keyword",
        "source_rule_id": rule_id,
    }


def test_durable_folder_backfill_preserves_manual_assignment(temp_db):
    target_project = project_service.create_project("Target")
    manual_project = project_service.create_project("Manual")
    eligible = _closed_activity(path=r"D:\Matter\eligible.docx")
    manual = _closed_activity(path=r"D:\Matter\manual.docx")
    assign_activity_project(manual, manual_project, manual=True)
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Matter",
        target_project,
    )

    result = rule_api.backfill_project_rule("folder", rule_id)

    assert result["ok"] is True
    assert _assignment(eligible)["project_id"] == target_project
    assert _assignment(eligible)["source_rule_id"] == rule_id
    assert _assignment(manual)["project_id"] == manual_project
    assert _assignment(manual)["is_manual"] == 1


def test_rule_identity_is_composite_when_numeric_ids_overlap(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("token", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )

    keyword = rule_api.preview_project_rule_impact("keyword", keyword_id)
    folder = rule_api.preview_project_rule_impact("folder", folder_id)

    assert keyword["ok"] is True
    assert keyword["impact"]["rule"]["kind"] == "keyword"
    assert folder["ok"] is True
    assert folder["impact"]["rule"]["kind"] == "folder"


def test_preview_and_backfill_reject_missing_ids_per_rule_type(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("token", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )
    missing_keyword_id = keyword_id + 1000
    missing_folder_id = folder_id + 1000

    for rule_type, missing_id in (
        ("keyword", missing_keyword_id),
        ("folder", missing_folder_id),
    ):
        assert rule_api.preview_project_rule_impact(rule_type, missing_id) == {
            "ok": False,
            "error": "not_found",
        }
        assert rule_api.backfill_project_rule(rule_type, missing_id) == {
            "ok": False,
            "error": "not_found",
        }


def test_rule_impact_api_validates_inputs(temp_db):
    for rule_type, rule_id in (
        ("unknown", 1),
        ("keyword", 0),
        ("keyword", True),
        ([], 1),
    ):
        assert rule_api.preview_project_rule_impact(rule_type, rule_id) == {
            "ok": False,
            "error": "invalid_input",
        }
        assert rule_api.backfill_project_rule(rule_type, rule_id) == {
            "ok": False,
            "error": "invalid_input",
        }
