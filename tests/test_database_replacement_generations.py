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
    settings_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _generations() -> dict[DataGenerationNamespace, int]:
    with get_connection() as conn:
        return {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in DataGenerationNamespace
        }


def test_clear_all_advances_only_replacement_epoch_once(temp_db):
    privacy_gate_service.accept_privacy_notice()
    project_service.create_project("Replacement Source")
    before = _generations()

    database_maintenance_service.clear_all_live_data()

    after = _generations()
    assert after[DataGenerationNamespace.DATABASE_REPLACEMENT] == (
        before[DataGenerationNamespace.DATABASE_REPLACEMENT] + 1
    )
    for namespace in DataGenerationNamespace:
        if namespace is DataGenerationNamespace.DATABASE_REPLACEMENT:
            continue
        assert after[namespace] == before[namespace]
    assert privacy_gate_service.is_privacy_notice_accepted() is True


def test_ordinary_domain_writes_do_not_advance_replacement(temp_db):
    before = _generations()

    settings_service.set_setting("ui_refresh_seconds", "77")
    project_service.create_project("Ordinary Domain Write")
    privacy_gate_service.accept_privacy_notice()

    after = _generations()
    assert after[DataGenerationNamespace.DATABASE_REPLACEMENT] == before[
        DataGenerationNamespace.DATABASE_REPLACEMENT
    ]
    assert after[DataGenerationNamespace.SETTINGS] > before[
        DataGenerationNamespace.SETTINGS
    ]
    assert after[DataGenerationNamespace.CLASSIFICATION_CATALOG] > before[
        DataGenerationNamespace.CLASSIFICATION_CATALOG
    ]
    assert after[DataGenerationNamespace.PRIVACY_CATALOG] > before[
        DataGenerationNamespace.PRIVACY_CATALOG
    ]


def test_replacement_repository_advances_above_live_floor_and_rolls_back(temp_db):
    before = _generations()[DataGenerationNamespace.DATABASE_REPLACEMENT]
    with get_connection() as conn:
        conn.execute("BEGIN")
        values = DataGenerationRepository.bump_replacement(
            conn,
            minimum_value=before + 20,
        )
        assert values == {
            DataGenerationNamespace.DATABASE_REPLACEMENT: before + 21
        }
        conn.rollback()

    assert _generations()[DataGenerationNamespace.DATABASE_REPLACEMENT] == before


def test_clear_all_refreshes_generation_backed_settings_cache(temp_db):
    settings_service.set_setting("ui_refresh_seconds", "77")
    assert settings_service.get_setting("ui_refresh_seconds") == "77"

    database_maintenance_service.clear_all_live_data()

    assert settings_service.get_setting("ui_refresh_seconds") == "10"


def test_replacement_generation_failure_rolls_back_data_and_generations(
    temp_db,
    monkeypatch,
):
    privacy_gate_service.accept_privacy_notice()
    project_id = project_service.create_project("Must Survive")
    before = _generations()
    original = database_maintenance_service.publish_database_replacement

    def fail_after_generation_write(conn):
        original(conn)
        raise RuntimeError("generation_publish_failed")

    monkeypatch.setattr(
        database_maintenance_service,
        "publish_database_replacement",
        fail_after_generation_write,
    )

    with pytest.raises(RuntimeError, match="generation_publish_failed"):
        database_maintenance_service.clear_all_live_data()

    assert _generations() == before
    assert project_service.get_project(project_id) is not None
    assert privacy_gate_service.is_privacy_notice_accepted() is True
