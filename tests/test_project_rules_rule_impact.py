"""Rule impact preview and durable single-rule history job contracts."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from tests.support import activity_factory as activity_service
from tests.support.db_helpers import assign_activity_project
from worktrace.api import rule_api
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
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\CaseA",
        project_id,
    )
    activity_id = _closed_activity(
        title=r"C:\Secret\clipboard SELECT",
        path=r"D:\CaseA\Doc.docx",
    )

    before = _assignment(activity_id)
    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    after = _assignment(activity_id)

    assert before == after
    assert result["rule"] == {
        "kind": "folder",
        "id": rule_id,
        "enabled": True,
        "project_id": project_id,
        "project_name": "Folder Project",
        "target": r"D:\CaseA",
        "project_available": True,
    }
    assert result["counts"]["matched_count"] == 1
    assert result["counts"]["would_update_count"] == 1
    assert result["samples"][0]["activity_id"] == activity_id
    serialized = json.dumps(result, ensure_ascii=False).casefold()
    for secret in ("c:\\secret", "clipboard", "select", "window_title", "path_hint"):
        assert secret not in serialized


def test_preview_keyword_rule_reports_skip_classes(temp_db):
    project_id = project_service.create_project("Keyword Project")
    rule_id = rule_service.create_rule("invoice", project_id)
    eligible = _closed_activity(title="invoice.xlsx - Excel")
    manual = _closed_activity(title="invoice manual.xlsx - Excel")
    hidden = _closed_activity(title="invoice hidden.xlsx - Excel")
    non_normal = _closed_activity(title="invoice idle", status="idle")
    assign_activity_project(manual, project_id, manual=True)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1 WHERE id = ?",
            (hidden,),
        )

    result = rule_impact_service.preview_rule_impact("keyword", rule_id)

    assert result["rule"]["target"] == "invoice"
    assert result["counts"]["matched_count"] == 1
    assert result["counts"]["would_update_count"] == 1
    assert result["counts"]["manual_skipped_count"] == 1
    assert result["counts"]["hidden_skipped_count"] == 1
    assert result["counts"]["non_normal_skipped_count"] == 1
    assert result["samples"][0]["activity_id"] == eligible


def test_disabled_rule_preview_is_zero_and_does_not_write(temp_db):
    project_id = project_service.create_project("Disabled")
    rule_id = rule_service.create_rule("disabled-token", project_id)
    activity_id = _closed_activity(title="disabled-token.docx - Word")
    rule_service.set_rule_enabled(rule_id, False)

    result = rule_impact_service.preview_rule_impact("keyword", rule_id)

    assert result["rule"]["enabled"] is False
    assert result["counts"]["would_update_count"] == 0
    assert result["samples"] == []
    assert _assignment(activity_id)["project_id"] != project_id


def test_durable_keyword_backfill_records_exact_rule_origin(temp_db):
    project_id = project_service.create_project("Client")
    rule_id = rule_service.create_rule("spec", project_id)
    activity_id = _closed_activity(title="spec document.docx - Word")

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
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Matter",
        target_project,
    )
    eligible = _closed_activity(path=r"D:\Matter\eligible.docx")
    manual = _closed_activity(path=r"D:\Matter\manual.docx")
    assign_activity_project(manual, manual_project, manual=True)

    result = rule_api.backfill_project_rule("folder", rule_id)

    assert result["ok"] is True
    assert _assignment(eligible)["project_id"] == target_project
    assert _assignment(eligible)["source_rule_id"] == rule_id
    assert _assignment(manual)["project_id"] == manual_project
    assert _assignment(manual)["is_manual"] == 1


def test_preview_and_backfill_reject_cross_type_ids(temp_db):
    project_id = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("token", project_id)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project_id,
    )

    assert rule_api.preview_project_rule_impact("folder", keyword_id) == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.preview_project_rule_impact("keyword", folder_id) == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.backfill_project_rule("folder", keyword_id) == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.backfill_project_rule("keyword", folder_id) == {
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
