from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "worktrace" / "services"


def test_project_service_does_not_own_cross_domain_delete_sql() -> None:
    source = (SERVICES / "project_service.py").read_text(encoding="utf-8")
    forbidden = (
        "history_mutation_job",
        "history_mutation_job_rule",
        "assignment_command_service",
        "rule_catalog_command_service",
        "SELECT id FROM project_rule WHERE project_id",
        "SELECT id FROM folder_project_rule WHERE project_id",
    )
    for marker in forbidden:
        assert marker not in source, f"project_service owns cross-domain delete detail: {marker}"

    assert "delete_project_identity_in_transaction" in source
    assert "project_deletion_command_service.delete_project" in source


def test_project_deletion_workflow_keeps_one_root_unit_of_work() -> None:
    source = (SERVICES / "project_deletion_command_service.py").read_text(
        encoding="utf-8"
    )
    assert "with DomainUnitOfWork(" in source
    assert "release_project_assignments_in_transaction" in source
    assert "list_project_rule_refs_in_transaction" in source
    assert "has_active_jobs_for_rule_refs_in_transaction" in source
    assert "delete_rule_in_transaction" in source
    assert "delete_project_identity_in_transaction" in source
