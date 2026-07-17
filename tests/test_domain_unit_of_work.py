from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.services import activity_lifecycle_service

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


def _generation(namespace: DataGenerationNamespace) -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(conn, namespace)


def test_deeply_nested_unit_of_work_commits_data_and_effect_once(temp_db):
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "INSERT INTO session_boundary(occurred_at, reason, created_at) "
            "VALUES (?, ?, ?)",
            ("2026-07-17 09:00:00", "test", "2026-07-17 09:00:00"),
        )
        outer.mark_changed()
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as middle:
            assert middle.connection is outer.connection
            with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as inner:
                assert inner.connection is outer.connection
                inner.mark_changed()

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before + 1


def test_nested_failure_marks_root_transaction_rollback_only(temp_db):
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "INSERT INTO session_boundary(occurred_at, reason, created_at) "
            "VALUES (?, ?, ?)",
            ("2026-07-17 10:00:00", "rollback", "2026-07-17 10:00:00"),
        )
        outer.mark_changed()
        try:
            with DomainUnitOfWork() as inner:
                assert inner.connection is outer.connection
                raise RuntimeError("rollback-contract")
        except RuntimeError as exc:
            assert str(exc) == "rollback-contract"

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM session_boundary WHERE reason = ?",
            ("rollback",),
        ).fetchone() is None


def test_non_report_effect_is_published_explicitly(temp_db):
    settings_before = _generation(DataGenerationNamespace.SETTINGS)
    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with DomainUnitOfWork((DataGenerationNamespace.SETTINGS,)) as uow:
        uow.connection.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            ("ui_refresh_seconds", "77", "2026-07-17 10:30:00"),
        )
        uow.mark_changed()

    assert _generation(DataGenerationNamespace.SETTINGS) == settings_before + 1
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before


def test_activity_checkpoint_does_not_publish_structure_generation(temp_db):
    activity_id = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-17 11:00:00",
        source="auto",
        payload={
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "UoW.docx",
        },
    )
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    assert activity_lifecycle_service.checkpoint_activity(activity_id, 30) is True
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before


def test_no_op_close_does_not_publish_structure_generation(temp_db):
    activity_id = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-17 12:00:00",
        source="auto",
        payload={
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "NoOp.docx",
        },
    )
    activity_lifecycle_service.close_activity(activity_id, "2026-07-17 12:10:00")
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    activity_lifecycle_service.close_activity(activity_id, "2026-07-17 12:10:00")

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before
