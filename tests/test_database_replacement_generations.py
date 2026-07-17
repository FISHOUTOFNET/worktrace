from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.services import (
    database_maintenance_service,
    privacy_gate_service,
    project_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _generations() -> dict[DataGenerationNamespace, int]:
    with get_connection() as conn:
        return {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in DataGenerationNamespace
        }


def test_clear_all_invalidates_every_generation_once(temp_db):
    privacy_gate_service.accept_privacy_notice()
    project_service.create_project("Replacement Source")
    before = _generations()

    database_maintenance_service.clear_all_live_data()

    after = _generations()
    assert {
        namespace: after[namespace] - before[namespace]
        for namespace in DataGenerationNamespace
    } == {namespace: 1 for namespace in DataGenerationNamespace}
    assert privacy_gate_service.is_privacy_notice_accepted() is True


def test_replacement_generation_failure_rolls_back_data_and_generations(
    temp_db,
    monkeypatch,
):
    privacy_gate_service.accept_privacy_notice()
    project_id = project_service.create_project("Must Survive")
    before = _generations()
    original = privacy_gate_service.publish_database_replacement

    def fail_after_generation_write(conn):
        original(conn)
        raise RuntimeError("generation_publish_failed")

    monkeypatch.setattr(
        privacy_gate_service,
        "publish_database_replacement",
        fail_after_generation_write,
    )

    with pytest.raises(RuntimeError, match="generation_publish_failed"):
        database_maintenance_service.clear_all_live_data()

    assert _generations() == before
    assert project_service.get_project(project_id) is not None
    assert privacy_gate_service.is_privacy_notice_accepted() is True
