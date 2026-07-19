from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.services import folder_rule_service, project_service, rule_service
from worktrace.services import rule_catalog_command_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _generation(namespace: DataGenerationNamespace) -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(conn, namespace)


def test_project_create_publishes_catalog_and_report_only(temp_db):
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)

    project_service.create_project("Catalog Client")

    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before + 1
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before + 1
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before


def test_project_semantic_no_op_does_not_publish_generation(temp_db):
    project_id = project_service.create_project(
        "Stable Client",
        "Stable description",
        "中文",
    )
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    project_service.update_project(
        project_id,
        "Stable Client",
        "Stable description",
        "中文",
    )

    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before


def test_normal_keyword_rule_does_not_invalidate_privacy_or_report(temp_db):
    project_id = project_service.create_project("Keyword Client")
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)
    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    rule_service.create_rule("keyword-uow", project_id)

    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before + 1
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before


def test_excluded_keyword_rule_adds_privacy_effect(temp_db):
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)

    _rule_id, excluded_id = rule_catalog_command_service.create_excluded_keyword_rule(
        "private-keyword-uow"
    )

    assert excluded_id > 0
    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before + 1
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before + 1


def test_folder_rule_semantic_no_op_does_not_publish_generation(temp_db):
    project_id = project_service.create_project("Folder Client")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        "D:\\CatalogUow",
        project_id,
        True,
    )
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)

    repeated = folder_rule_service.create_or_update_folder_rule(
        "d:/CatalogUow/",
        project_id,
        True,
    )

    assert repeated == rule_id
    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before


def test_excluded_folder_rule_adds_privacy_effect(temp_db):
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)

    _rule_id, excluded_id = (
        rule_catalog_command_service.create_or_update_excluded_folder_rule(
            "D:\\PrivateCatalogUow",
            True,
        )
    )

    assert excluded_id > 0
    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before + 1
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before + 1


@pytest.mark.parametrize(
    ("old_owner", "new_owner", "privacy_delta"),
    [
        ("normal_a", "normal_b", 0),
        ("normal_a", "excluded", 1),
        ("excluded", "normal_a", 1),
    ],
)
def test_normalized_folder_upsert_accounts_for_old_and_new_owner_effects(
    temp_db,
    old_owner,
    new_owner,
    privacy_delta,
):
    owners = {
        "normal_a": project_service.create_project("Folder Owner A"),
        "normal_b": project_service.create_project("Folder Owner B"),
    }
    if old_owner == "excluded":
        rule_id, _excluded_id = (
            rule_catalog_command_service.create_or_update_excluded_folder_rule(
                "D:\\OwnerMigration",
                True,
            )
        )
    else:
        rule_id = folder_rule_service.create_or_update_folder_rule(
            "D:\\OwnerMigration",
            owners[old_owner],
            True,
        )
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)

    if new_owner == "excluded":
        repeated_id, _excluded_id = (
            rule_catalog_command_service.create_or_update_excluded_folder_rule(
                "d:/OwnerMigration/",
                True,
            )
        )
    else:
        repeated_id = folder_rule_service.create_or_update_folder_rule(
            "d:/OwnerMigration/",
            owners[new_owner],
            True,
        )

    assert repeated_id == rule_id
    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before + 1
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before + privacy_delta


def test_excluded_folder_semantic_change_bumps_privacy_once(temp_db):
    rule_id, _excluded_id = (
        rule_catalog_command_service.create_or_update_excluded_folder_rule(
            "D:\\ExcludedOwner",
            True,
        )
    )
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)

    folder_rule_service.update_folder_rule(rule_id, "D:\\ExcludedOwner", False)

    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before + 1
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before + 1
