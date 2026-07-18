from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection, now_str
from worktrace.report_generation_classifier import report_structure_classifier_scope
from worktrace.services import activity_lifecycle_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.serial]


def _generation() -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )


def test_structure_generation_is_durable_and_ignores_duration_checkpoint(temp_db):
    before = _generation()
    activity_id = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-16 09:00:00",
        source="auto",
        payload={
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "Report.docx",
        },
    )
    after_insert = _generation()

    assert after_insert > before

    assert activity_lifecycle_service.checkpoint_activity(activity_id, 30) is True
    assert _generation() == after_insert

    with report_structure_classifier_scope():
        with get_connection() as conn:
            conn.execute(
                "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
                ("idle", now_str(), activity_id),
            )

    assert _generation() > after_insert
