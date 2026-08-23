from __future__ import annotations

import pytest

from worktrace.api import project_api
from worktrace.api.application_capabilities import RulesApplicationService
from worktrace.integrations.fd_work.binding_repository import FDWorkBindingRepository
from worktrace.integrations.fd_work.binding_service import FDWorkBindingService
from worktrace.integrations.fd_work.contracts import FDWorkEntryError
from worktrace.integrations.fd_work.integration_service import SelectionClaim
from worktrace.integrations.fd_work.project_use_cases import (
    CreateFDWorkBoundProject,
    RebindFDWorkProject,
)
from worktrace.services import project_service


pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.security_privacy]


class _Integration:
    def __init__(self, binding_service):
        self.binding_service = binding_service
        self.enabled = True
        self.claimed = set()

    def validate_case_selection(self, token, expected):
        labels = {"token-a": "CASE A", "token-b": "CASE B"}
        if token not in labels:
            raise FDWorkEntryError("case_selection_expired")
        if expected.strip() not in {labels[token], "typed"}:
            raise FDWorkEntryError("case_selection_mismatch")
        return labels[token]

    def discard_case_selection(self, _token):
        return None

    def claim_case_selection(self, token, expected):
        label = self.validate_case_selection(token, expected)
        if token in self.claimed:
            raise FDWorkEntryError("fd_work_busy")
        self.claimed.add(token)
        return SelectionClaim(token, label, f"claim-{token}")

    def complete_case_selection_claim(self, claim):
        self.claimed.discard(claim.token)

    def release_case_selection_claim(self, claim):
        self.claimed.discard(claim.token)

    def create_bound_project(self, name, description, language, selection_token):
        return CreateFDWorkBoundProject(
            selection_service=self,
            binding_service=self.binding_service,
            create_project=project_api.create_project_for_rules,
            project_reader=project_api.get_project,
        ).execute(name, description, language, selection_token)

    def rebind_project(
        self, project_id, name, description, language, selection_token
    ):
        return RebindFDWorkProject(
            selection_service=self,
            binding_service=self.binding_service,
            update_project=project_api.update_project_for_rules,
            project_reader=project_api.get_project,
        ).execute(project_id, name, description, language, selection_token)

    def bind_project(self, project_id, label):
        self.binding_service.bind_project(project_id, label)

    def clear_project_binding(self, project_id):
        self.binding_service.clear_binding(project_id)

    def list_bound_project_ids(self):
        return self.binding_service.list_bound_project_ids()

    def get_settings_status(self):
        return {"enabled": self.enabled}

    def list_project_identities(self, projects):
        bound_ids = self.list_bound_project_ids() if self.enabled else set()
        return [
            {
                **dict(project),
                "external_identity_bound": project["id"] in bound_ids,
            }
            for project in projects
        ]

    @staticmethod
    def _identity_result(result):
        binding = result.pop("fd_work_binding", None)
        if binding is not None:
            result["external_identity_binding"] = binding
        return result

    def create_project(self, name, description, language, proof):
        if self.enabled and proof is None:
            return {"ok": False, "error": "case_selection_required"}
        if proof is not None:
            return self._identity_result(
                self.create_bound_project(name, description, language, proof)
            )
        result = project_api.create_project_for_rules(name, description, language)
        if result.get("ok") is True:
            result["external_identity_binding"] = {"bound": False}
        return result

    def update_project(self, project_id, name, description, language, proof):
        current = project_api.get_project(project_id)
        changed = bool(current) and current["name"] != name.strip()
        if self.enabled and changed and proof is None:
            return {"ok": False, "error": "case_selection_required"}
        if proof is not None:
            return self._identity_result(
                self.rebind_project(project_id, name, description, language, proof)
            )
        result = project_api.update_project_for_rules(
            project_id, name, description, language
        )
        if result.get("ok") is True:
            if changed and not self.enabled:
                self.clear_project_binding(project_id)
            result["external_identity_binding"] = {
                "bound": project_id in self.list_bound_project_ids()
            }
        return result

    def clear_project_identity(self, project_id):
        self.clear_project_binding(project_id)
        return {"ok": True, "external_identity_binding": {"bound": False}}

    def after_project_deleted(self, project_id):
        self.clear_project_binding(project_id)
        return {"bound": False}


def _binding_service(path):
    return FDWorkBindingService(
        FDWorkBindingRepository(path),
        project_reader=project_api.get_project,
        project_list_reader=project_service.list_user_project_identities,
    )


def test_real_project_writes_follow_binding_lifecycle_and_survive_service_restart(
    temp_db, tmp_path
):
    state_path = tmp_path / "plugins" / "fd_work" / "state.db"
    integration = _Integration(_binding_service(state_path))
    rules = RulesApplicationService(project_identity=integration)

    integration.enabled = False
    ordinary = rules.create_project_for_rules("Ordinary", "", "中文")
    integration.enabled = True
    selected = rules.create_project_for_rules("typed", "", "中文", "token-a")
    ordinary_id = ordinary["project"]["id"]
    selected_id = selected["project"]["id"]

    assert ordinary["external_identity_binding"] == {"bound": False}
    assert selected["project"]["name"] == "CASE A"
    assert selected["external_identity_binding"] == {"bound": True, "verified": True}
    restarted = _binding_service(state_path)
    assert restarted.list_bound_project_ids() == {selected_id}

    integration.binding_service = restarted
    description = rules.update_project_for_rules(
        selected_id, "CASE A", "description only", "中文"
    )
    assert description["external_identity_binding"] == {"bound": True}

    rejected_rename = rules.update_project_for_rules(
        selected_id, "Manual", "description only", "中文"
    )
    assert rejected_rename == {"ok": False, "error": "case_selection_required"}
    assert restarted.list_bound_project_ids() == {selected_id}

    integration.enabled = False
    renamed = rules.update_project_for_rules(
        selected_id, "Manual", "description only", "中文"
    )
    assert renamed["external_identity_binding"] == {"bound": False}
    assert restarted.list_bound_project_ids() == set()

    integration.enabled = True
    rebound = rules.update_project_for_rules(
        selected_id, "typed", "description only", "中文", "token-b"
    )
    assert rebound["project"]["name"] == "CASE B"
    assert rebound["external_identity_binding"] == {"bound": True, "verified": True}

    integration.enabled = False
    integration.enabled = True
    assert restarted.list_bound_project_ids() == {selected_id}

    deleted = rules.delete_project_for_rules(selected_id)
    assert deleted["ok"] is True
    assert restarted.list_bound_project_ids() == set()
    assert ordinary_id not in restarted.list_bound_project_ids()


def test_legacy_project_name_is_never_inferred_as_a_binding(temp_db, tmp_path):
    project_service.create_project("CASE A")
    service = _binding_service(tmp_path / "state.db")

    assert service.list_bound_project_ids() == set()
    assert not (tmp_path / "state.db").exists()


def test_archiving_preserves_binding_identity(temp_db, tmp_path):
    state_path = tmp_path / "state.db"
    integration = _Integration(_binding_service(state_path))
    rules = RulesApplicationService(project_identity=integration)
    selected = rules.create_project_for_rules("typed", "", "中文", "token-a")
    project_id = selected["project"]["id"]

    project_service.archive_project(project_id)

    assert integration.binding_service.list_bound_project_ids() == {project_id}
