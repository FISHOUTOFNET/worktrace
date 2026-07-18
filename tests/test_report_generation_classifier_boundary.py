from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.report_generation_classifier import (
    ReportStructureSqlClassification,
    classify_report_structure_sql,
    sql_affects_report_structure,
    report_structure_classifier_scope,
)
from worktrace.data_generation_repository import DataGenerationNamespace, DataGenerationRepository
from worktrace.db import get_connection, now_str
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.services import activity_lifecycle_service


pytestmark = pytest.mark.db


def _generation() -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(
            conn, DataGenerationNamespace.REPORT_STRUCTURE
        )


def _activity() -> int:
    return activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-17 09:00:00",
        source="auto",
        payload={
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "Classifier.docx",
        },
    )


def test_database_connection_does_not_define_report_policy_tables():
    source = Path("worktrace/db.py").read_text(encoding="utf-8")
    assert "_REPORT_STRUCTURE_TABLES" not in source
    assert "_REPORT_STRUCTURE_SETTINGS" not in source
    assert "def _classify_report_structure_sql" not in source


def test_classifier_ignores_open_duration_checkpoint():
    sql = "UPDATE activity_log SET duration_seconds = ?, updated_at = ? WHERE id = ?"
    assert classify_report_structure_sql(sql) is ReportStructureSqlClassification.NONE
    assert sql_affects_report_structure(sql, (30, "2026-07-17 09:00:00", 1)) is False


def test_classifier_tracks_structural_activity_and_report_setting_changes():
    assert sql_affects_report_structure(
        "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
        ("idle", "2026-07-17 09:00:00", 1),
    ) is True
    assert sql_affects_report_structure(
        "UPDATE settings SET value = ? WHERE key = ?",
        ("20", "context_carry_minutes"),
    ) is True
    assert sql_affects_report_structure(
        "UPDATE settings SET value = ? WHERE key = ?",
        ("running", "collector_status"),
    ) is False


def test_classifier_tracks_project_display_fact_changes():
    assert sql_affects_report_structure(
        "UPDATE project SET name = ?, updated_at = ? WHERE id = ?",
        ("Renamed", "2026-07-17 12:00:00", 7),
    ) is True


def test_connection_classifier_requires_explicit_scope(temp_db):
    activity_id = _activity()
    before = _generation()
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
            ("idle", now_str(), activity_id),
        )
    assert _generation() == before

    with report_structure_classifier_scope():
        with get_connection() as conn:
            conn.execute(
                "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
                ("normal", now_str(), activity_id),
            )
    assert _generation() == before + 1


def test_classifier_does_not_double_publish_explicit_uow(temp_db):
    activity_id = _activity()
    before = _generation()
    with report_structure_classifier_scope():
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
            uow.connection.execute(
                "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
                ("idle", now_str(), activity_id),
            )
            uow.mark_changed()
    assert _generation() == before + 1
