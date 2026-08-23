from __future__ import annotations

from dataclasses import dataclass

import pytest

from worktrace.integrations.fd_work.binding_repository import FDWorkBindingRepository
from worktrace.integrations.fd_work.binding_service import FDWorkBindingService
from worktrace.integrations.fd_work.case_identity import case_label_hash
from worktrace.integrations.fd_work.project_use_cases import (
    CreateFDWorkBoundProject,
    RebindFDWorkProject,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


@dataclass(frozen=True)
class _Claim:
    token: str
    label: str
    claim_id: str


class _Selections:
    def __init__(self) -> None:
        self.claim = _Claim("selection-token", "TEST MATTER A", "claim-1")
        self.completed = []
        self.released = []

    def claim_case_selection(self, token, expected):
        assert (token, expected) == ("selection-token", "typed")
        return self.claim

    def complete_case_selection_claim(self, claim):
        self.completed.append(claim)

    def release_case_selection_claim(self, claim):
        self.released.append(claim)


def _use_case(tmp_path, *, fail_binding=False):
    projects = {}
    selections = _Selections()
    repository = FDWorkBindingRepository(tmp_path / "state.db")
    binding_service = FDWorkBindingService(
        repository,
        project_reader=lambda project_id: projects.get(project_id),
        project_list_reader=lambda: list(projects.values()),
    )
    if fail_binding:
        original_bind = binding_service.bind_project
        bind_attempts = [0]

        def fail_first_bind(*args, **kwargs):
            bind_attempts[0] += 1
            if bind_attempts[0] == 1:
                raise RuntimeError("write failed")
            return original_bind(*args, **kwargs)

        binding_service.bind_project = fail_first_bind

    def create_project(name, description, language):
        projects[41] = {
            "id": 41,
            "name": name,
            "description": description,
            "language": language,
            "created_at": "2026-08-04 10:00:00",
        }
        return {"ok": True, "project": {"id": 41, "name": name}}

    use_case = CreateFDWorkBoundProject(
        selection_service=selections,
        binding_service=binding_service,
        create_project=create_project,
        project_reader=lambda project_id: projects.get(project_id),
        operation_id_factory=lambda: "operation-1",
        clock=lambda: "2026-08-04T02:00:00+00:00",
    )
    return use_case, selections, repository, projects


def test_create_bound_project_requires_project_and_binding_readback(tmp_path):
    use_case, selections, repository, projects = _use_case(tmp_path)

    result = use_case.execute("typed", "description", "中文", "selection-token")

    assert result["ok"] is True
    assert result["project"]["id"] == 41
    assert result["project"]["name"] == "TEST MATTER A"
    assert result["fd_work_binding"] == {"bound": True, "verified": True}
    assert projects[41]["name"] == "TEST MATTER A"
    assert repository.get_binding(41) is not None
    assert repository.list_pending_operations() == []
    assert selections.completed == [selections.claim]
    assert selections.released == []


def test_create_bound_project_never_reports_partial_success(tmp_path):
    use_case, selections, repository, projects = _use_case(
        tmp_path, fail_binding=True
    )

    result = use_case.execute("typed", "", "中文", "selection-token")

    assert result["ok"] is False
    assert result["error"] == "fd_work_persistence_unconfirmed"
    assert result.get("project") is None
    assert projects[41]["name"] == "TEST MATTER A"
    assert repository.get_binding(41) is None
    assert repository.get_pending_operation("operation-1") is not None
    assert selections.completed == []
    assert selections.released == []


def _rebind_use_case(tmp_path, *, fail_binding=False, fail_restore=False):
    projects = {
        7: {
            "id": 7,
            "name": "OLD MATTER",
            "description": "old description",
            "language": "中文",
            "created_at": "2026-08-04 09:00:00",
        }
    }
    selections = _Selections()
    repository = FDWorkBindingRepository(tmp_path / "state.db")
    repository.bind_project(
        7,
        "2026-08-04 09:00:00",
        case_label_hash("OLD MATTER"),
        5,
    )
    binding_service = FDWorkBindingService(
        repository,
        project_reader=lambda project_id: projects.get(project_id),
        project_list_reader=lambda: list(projects.values()),
    )

    def update_project(project_id, name, description, language):
        projects[project_id].update(
            name=name, description=description, language=language
        )
        return {"ok": True, "project": {"id": project_id, "name": name}}

    if fail_binding:
        original_bind = binding_service.bind_project
        bind_attempts = [0]

        def fail_first_bind(*args, **kwargs):
            bind_attempts[0] += 1
            if bind_attempts[0] == 1 or fail_restore:
                raise RuntimeError("write failed")
            return original_bind(*args, **kwargs)

        binding_service.bind_project = fail_first_bind
    use_case = RebindFDWorkProject(
        selection_service=selections,
        binding_service=binding_service,
        update_project=update_project,
        project_reader=lambda project_id: projects.get(project_id),
        operation_id_factory=lambda: "operation-rebind",
        clock=lambda: "2026-08-04T02:00:00+00:00",
    )
    return use_case, selections, repository, projects


def test_rebind_project_requires_new_name_and_binding_readback(tmp_path):
    use_case, selections, repository, projects = _rebind_use_case(tmp_path)

    result = use_case.execute(7, "typed", "new description", "English", "selection-token")

    assert result["ok"] is True
    assert result["project"]["name"] == "TEST MATTER A"
    assert result["fd_work_binding"] == {"bound": True, "verified": True}
    assert projects[7]["name"] == "TEST MATTER A"
    assert repository.get_binding(7).bound_name_hash == case_label_hash("TEST MATTER A")
    assert repository.list_pending_operations() == []
    assert selections.completed == [selections.claim]


def test_rebind_failure_restores_previous_project_and_binding(tmp_path):
    use_case, selections, repository, projects = _rebind_use_case(
        tmp_path, fail_binding=True
    )

    result = use_case.execute(7, "typed", "new description", "English", "selection-token")

    assert result == {"ok": False, "error": "fd_work_persistence_unconfirmed"}
    assert projects[7]["name"] == "OLD MATTER"
    assert projects[7]["description"] == "old description"
    assert repository.get_binding(7).bound_name_hash == case_label_hash("OLD MATTER")
    assert repository.list_pending_operations() == []
    assert selections.released == [selections.claim]


def test_rebind_reports_inconsistent_state_when_restore_cannot_be_proven(tmp_path):
    use_case, selections, repository, projects = _rebind_use_case(
        tmp_path, fail_binding=True, fail_restore=True
    )

    result = use_case.execute(7, "typed", "new description", "English", "selection-token")

    assert result == {"ok": False, "error": "fd_work_inconsistent_state"}
    assert projects[7]["name"] == "OLD MATTER"
    assert repository.get_pending_operation("operation-rebind") is not None
    assert selections.released == []
