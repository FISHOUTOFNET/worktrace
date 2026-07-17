from __future__ import annotations

import pytest

from worktrace.constants import EXCLUDED_PROJECT
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.services import folder_rule_service, project_service, rule_service

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
    excluded = project_service.get_project_by_name(EXCLUDED_PROJECT)
    assert excluded is not None
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)

    rule_service.create_rule("private-keyword-uow", int(excluded["id"]))

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
        "D:\\CatalogUow",
        project_id,
        True,
    )

    assert repeated == rule_id
    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before


def test_excluded_folder_rule_adds_privacy_effect(temp_db):
    excluded = project_service.get_project_by_name(EXCLUDED_PROJECT)
    assert excluded is not None
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)

    folder_rule_service.create_or_update_folder_rule(
        "D:\\PrivateCatalogUow",
        int(excluded["id"]),
        True,
    )

    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before + 1
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before + 1
