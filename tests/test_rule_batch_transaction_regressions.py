from __future__ import annotations

import threading

import pytest

from tests.support.activity_factory import create_closed_activity
from worktrace.db import get_connection
from worktrace.services import (
    folder_rule_service,
    project_service,
    rule_batch_service,
    rule_service,
)
from worktrace.write_gate import DATABASE_WRITE_GATE

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-15"


def test_rule_batch_refreshes_generation_before_write_lock(temp_db):
    activity_id = create_closed_activity(
        day=DATE,
        start="13:00:00",
        end="13:10:00",
        app_name="Word",
        process_name="winword.exe",
        window_title="Word",
    )
    project_id = project_service.create_project("Generation Target")
    rule_id = rule_service.create_rule("Word", project_id)

    DATABASE_WRITE_GATE.note_current_thread_read()
    thread_errors: list[BaseException] = []

    def rotate_generation() -> None:
        try:
            with DATABASE_WRITE_GATE.draining() as lease:
                lease.promote()
        except BaseException as exc:  # pragma: no cover - assertion reports it
            thread_errors.append(exc)

    thread = threading.Thread(target=rotate_generation)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert thread_errors == []

    result = rule_batch_service.backfill_project_rules_batch(
        [{"rule_type": "keyword", "rule_id": rule_id}]
    )
    assert result["counts"]["updated_count"] == 1
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id, source, is_manual "
            "FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert assignment is not None
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "keyword_rule"
    assert int(assignment["is_manual"]) == 0


def test_rule_batch_applies_folder_and_keyword_in_one_transaction(temp_db):
    folder_project = project_service.create_project("Folder Target")
    keyword_project = project_service.create_project("Keyword Target")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        "D:\\BatchFolder",
        folder_project,
    )
    keyword_rule_id = rule_service.create_rule("batch-keyword", keyword_project)

    create_closed_activity(
        day=DATE,
        start="14:00:00",
        end="14:10:00",
        app_name="Word",
        process_name="winword.exe",
        window_title="Document.docx - Word",
        file_path_hint="D:\\BatchFolder\\Document.docx",
    )
    create_closed_activity(
        day=DATE,
        start="15:00:00",
        end="15:10:00",
        app_name="Excel",
        process_name="excel.exe",
        window_title="batch-keyword.xlsx - Excel",
    )

    result = rule_batch_service.backfill_project_rules_batch(
        [
            {"rule_type": "folder", "rule_id": folder_rule_id},
            {"rule_type": "keyword", "rule_id": keyword_rule_id},
        ]
    )

    assert result["counts"]["updated_count"] == 2
