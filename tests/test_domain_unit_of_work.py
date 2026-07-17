from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    ALL_DATA_GENERATION_NAMESPACES,
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.domain_unit_of_work import DomainUnitOfWork
from worktrace.mutation_effects import database_replacement_mutation
from worktrace.services import project_service, settings_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.serial]


def _generations() -> dict[DataGenerationNamespace, int]:
    with get_connection() as conn:
        return DataGenerationRepository.get_many(
            conn,
            ALL_DATA_GENERATION_NAMESPACES,
        )


def test_nested_units_merge_effects_and_commit_once(temp_db):
    before = _generations()
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)):
        with get_connection() as conn:
            conn.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                ("nested-a", "collector_status"),
            )
        with DomainUnitOfWork((DataGenerationNamespace.SETTINGS,)):
            with get_connection() as conn:
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    ("nested-b", "collector_health_state"),
                )
    after = _generations()
    assert after[DataGenerationNamespace.REPORT_STRUCTURE] == before[DataGenerationNamespace.REPORT_STRUCTURE] + 1
    assert after[DataGenerationNamespace.SETTINGS] == before[DataGenerationNamespace.SETTINGS] + 1
    for namespace in set(ALL_DATA_GENERATION_NAMESPACES) - {
        DataGenerationNamespace.REPORT_STRUCTURE,
        DataGenerationNamespace.SETTINGS,
    }:
        assert after[namespace] == before[namespace]


def test_data_and_generation_roll_back_together(temp_db):
    before = _generations()
    with get_connection() as conn:
        original = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("collector_status",),
        ).fetchone()["value"]

    with pytest.raises(RuntimeError, match="abort"):
        with DomainUnitOfWork((DataGenerationNamespace.SETTINGS,)):
            with get_connection() as conn:
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    ("should-rollback", "collector_status"),
                )
            raise RuntimeError("abort")

    with get_connection() as conn:
        current = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("collector_status",),
        ).fetchone()["value"]
    assert current == original
    assert _generations() == before


def test_write_without_declared_effect_is_rejected(temp_db):
    with pytest.raises(RuntimeError, match="domain_mutation_effect_required"):
        with DomainUnitOfWork():
            with get_connection() as conn:
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    ("missing-effect", "collector_status"),
                )


def test_classification_owner_bumps_only_declared_catalogs(temp_db):
    before = _generations()
    project_service.create_project("UoW Catalog")
    after = _generations()
    for namespace in (
        DataGenerationNamespace.REPORT_STRUCTURE,
        DataGenerationNamespace.CLASSIFICATION_CATALOG,
        DataGenerationNamespace.PRIVACY_CATALOG,
    ):
        assert after[namespace] == before[namespace] + 1
    assert after[DataGenerationNamespace.SETTINGS] == before[DataGenerationNamespace.SETTINGS]
    assert after[DataGenerationNamespace.DATABASE_REPLACEMENT] == before[DataGenerationNamespace.DATABASE_REPLACEMENT]


def test_setting_effects_are_semantic_and_keyed(temp_db):
    before = _generations()
    settings_service.set_setting("ui_refresh_seconds", "17")
    middle = _generations()
    assert middle[DataGenerationNamespace.SETTINGS] == before[DataGenerationNamespace.SETTINGS] + 1
    assert middle[DataGenerationNamespace.REPORT_STRUCTURE] == before[DataGenerationNamespace.REPORT_STRUCTURE]

    settings_service.set_setting("context_carry_minutes", "9")
    after = _generations()
    assert after[DataGenerationNamespace.SETTINGS] == middle[DataGenerationNamespace.SETTINGS] + 1
    assert after[DataGenerationNamespace.REPORT_STRUCTURE] == middle[DataGenerationNamespace.REPORT_STRUCTURE] + 1

    settings_service.set_setting("context_carry_minutes", "9")
    assert _generations() == after


def test_database_replacement_effect_bumps_every_namespace(temp_db):
    before = _generations()

    @database_replacement_mutation
    def replace_marker() -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                ("replacement", "collector_status"),
            )

    replace_marker()
    after = _generations()
    for namespace in ALL_DATA_GENERATION_NAMESPACES:
        assert after[namespace] == before[namespace] + 1
