from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.unit]


MIGRATED_FILES = (
    "test_activity_service.py",
    "test_timeline_service.py",
    "test_export_service.py",
    "test_statistics_service.py",
    "test_local_file_detector.py",
    "test_activity_resource_service.py",
    "test_continuity_gap_policy.py",
    "test_recovery_service.py",
    "test_clipboard_service.py",
    "test_wps_resource_classification.py",
    "test_project_inference_service.py",
    "test_rule_service.py",
    "test_folder_rule_service.py",
    "test_export_resource_fields.py",
    "test_project_inference_resource.py",
    "test_overview_bundle_and_export_contract.py",
    "test_privacy_resource_exclusion.py",
    "test_projection_plain_dto_contract.py",
    "test_report_structure_generation.py",
    "test_report_session_operations.py",
    "test_report_projection_cutover.py",
    "test_rule_history_application_service.py",
    "test_webview_bridge.py",
    "test_timeline_api_editing.py",
    "test_architecture_scalability_hardening.py",
)


def test_migrated_activity_fact_tests_use_test_only_facade() -> None:
    root = Path(__file__).resolve().parent
    violations: list[str] = []
    for name in MIGRATED_FILES:
        source = (root / name).read_text(encoding="utf-8")
        if "from tests.support import activity_factory as activity_service" not in source:
            violations.append(f"{name}: missing test activity facade import")
        if "from worktrace.services import activity_service" in source:
            violations.append(f"{name}: imports production activity_service")
        if "activity_service," in source and "from worktrace.services import (" in source:
            violations.append(f"{name}: imports production activity_service in grouped import")
    assert violations == []
