from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.services import activity_lifecycle_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract, pytest.mark.serial]


def _generation(namespace: DataGenerationNamespace) -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(conn, namespace)


def test_nested_unit_of_work_commits_data_and_effect_once(temp_db):
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as outer:
        outer.connection.execute(
            "INSERT INTO session_boundary(boundary_time, reason, created_at) VALUES (?, ?, ?)",
            ("2026-07-17 09:00:00", "test", "2026-07-17 09:00:00"),
        )
        outer.mark_changed()
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as inner:
            assert inner.connection is outer.connection
            inner.mark_changed()

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before + 1


def test_unit_of_work_rolls_back_data_and_generation(temp_db):
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    with pytest.raises(RuntimeError, match="rollback-contract"):
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
            uow.connection.execute(
                "INSERT INTO session_boundary(boundary_time, reason, created_at) VALUES (?, ?, ?)",
                ("2026-07-17 10:00:00", "rollback", "2026-07-17 10:00:00"),
            )
            uow.mark_changed()
            raise RuntimeError("rollback-contract")

    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM session_boundary WHERE reason = ?",
            ("rollback",),
        ).fetchone() is None


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
