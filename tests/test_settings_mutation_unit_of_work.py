from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.services import privacy_gate_service, settings_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _generation(namespace: DataGenerationNamespace) -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(conn, namespace)


def _all_generations() -> dict[DataGenerationNamespace, int]:
    return {namespace: _generation(namespace) for namespace in DataGenerationNamespace}


def test_operational_setting_does_not_publish_business_generation(temp_db):
    before = _all_generations()

    settings_service.set_setting("collector_status", "typed-uow-running")

    assert settings_service.get_setting("collector_status") == "typed-uow-running"
    assert _all_generations() == before


def test_user_setting_publishes_settings_only(temp_db):
    before = _all_generations()

    settings_service.set_setting("export_path", "D:\\TypedUow")

    after = _all_generations()
    assert after[DataGenerationNamespace.SETTINGS] == before[DataGenerationNamespace.SETTINGS] + 1
    for namespace in set(DataGenerationNamespace) - {DataGenerationNamespace.SETTINGS}:
        assert after[namespace] == before[namespace]


def test_report_setting_publishes_settings_and_report_once(temp_db):
    before = _all_generations()

    settings_service.set_setting("context_carry_minutes", "13")

    after = _all_generations()
    assert after[DataGenerationNamespace.SETTINGS] == before[DataGenerationNamespace.SETTINGS] + 1
    assert after[DataGenerationNamespace.REPORT_STRUCTURE] == before[DataGenerationNamespace.REPORT_STRUCTURE] + 1
    assert after[DataGenerationNamespace.PRIVACY_CATALOG] == before[DataGenerationNamespace.PRIVACY_CATALOG]
    assert after[DataGenerationNamespace.CLASSIFICATION_CATALOG] == before[DataGenerationNamespace.CLASSIFICATION_CATALOG]


def test_installation_privacy_acceptance_does_not_mutate_business_generations(temp_db):
    before = _all_generations()

    privacy_gate_service.accept_privacy_notice()

    after = _all_generations()
    assert privacy_gate_service.is_privacy_notice_accepted() is True
    assert after == before


def test_setting_semantic_no_op_publishes_nothing(temp_db):
    settings_service.set_setting("ui_refresh_seconds", "7")
    before = _all_generations()

    settings_service.set_setting("ui_refresh_seconds", "7")

    assert _all_generations() == before


def test_setting_classes_are_explicit_and_stable():
    assert settings_service.setting_mutation_class("collector_status") is settings_service.SettingMutationClass.OPERATIONAL
    assert settings_service.setting_mutation_class("collector_last_successful_observation_at") is settings_service.SettingMutationClass.OPERATIONAL
    assert settings_service.setting_mutation_class("maintenance.activity_resource_repair.v1") is settings_service.SettingMutationClass.OPERATIONAL
    assert settings_service.setting_mutation_class("clipboard_capture_enabled") is settings_service.SettingMutationClass.PRIVACY
    assert settings_service.setting_mutation_class("context_carry_minutes") is settings_service.SettingMutationClass.REPORT
    assert settings_service.setting_mutation_class("export_path") is settings_service.SettingMutationClass.USER
