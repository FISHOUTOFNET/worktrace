from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection, now_str
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.services import activity_lifecycle_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _generation() -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )


def _activity() -> int:
    return activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-17 09:00:00",
        source="auto",
        payload={
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "Explicit generation.docx",
        },
    )


def test_database_connection_has_no_report_policy_or_classifier_module():
    source = Path("worktrace/db.py").read_text(encoding="utf-8")
    assert "_REPORT_STRUCTURE_TABLES" not in source
    assert "_REPORT_STRUCTURE_SETTINGS" not in source
    assert "_classify_report_structure_sql" not in source
    assert not Path("worktrace/report_generation_classifier.py").exists()


def test_raw_connection_write_does_not_infer_report_generation(temp_db):
    activity_id = _activity()
    before = _generation()

    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )

    assert _generation() == before


def test_explicit_uow_publishes_declared_report_generation_once(temp_db):
    activity_id = _activity()
    before = _generation()

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        uow.connection.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )

    assert _generation() == before + 1


def test_explicit_uow_rollback_publishes_nothing(temp_db):
    activity_id = _activity()
    before = _generation()

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        uow.connection.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )
        uow.mark_rollback_only()

    assert _generation() == before
    with get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()["status"]
    assert status == "normal"


def test_nested_explicit_uow_coalesces_generation_publication(temp_db):
    activity_id = _activity()
    before = _generation()

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as inner:
            inner.connection.execute(
                "UPDATE activity_log SET window_title = ?, updated_at = ? WHERE id = ?",
                ("Renamed.docx", now_str(), activity_id),
            )

    assert _generation() == before + 1
