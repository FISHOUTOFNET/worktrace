from __future__ import annotations

import pytest

from worktrace.api import application_capabilities
from worktrace.api.application_capabilities import RulesApplicationService
from worktrace.api.external_project_identity import OptionalProjectIdentityCapability
from worktrace.integrations.fd_work.contracts import FDWorkEntryError


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _FDWork:
    def __init__(self, enabled=True, *, fail_bind=False, fail_clear=False):
        self.enabled = enabled
        self.fail_bind = fail_bind
        self.fail_clear = fail_clear
        self.discarded = []
        self.bound = []
        self.cleared = []
        self.bound_ids = {7}

    def get_settings_status(self):
        return {"enabled": self.enabled}

    def validate_case_selection(self, token, _expected):
        if not token:
            raise FDWorkEntryError("case_selection_required")
        if token == "expired":
            raise FDWorkEntryError("case_selection_expired")
        if token == "mismatch":
            raise FDWorkEntryError("case_selection_mismatch")
        return "CASE A" if token == "token-a" else "CASE B"

    def discard_case_selection(self, token):
        if token is not None:
            self.discarded.append(token)

    def bind_project(self, project_id, label):
        if self.fail_bind:
            raise FDWorkEntryError("binding_store_busy")
        self.bound.append((project_id, label))
        self.bound_ids.add(project_id)

    def clear_project_binding(self, project_id):
        if self.fail_clear:
            raise FDWorkEntryError("binding_store_busy")
        self.cleared.append(project_id)
        self.bound_ids.discard(project_id)

    def list_bound_project_ids(self):
        return set(self.bound_ids) if self.enabled else set()

    def create_bound_project(self, name, description, language, selection_token):
        canonical = self.validate_case_selection(selection_token, name)
        result = application_capabilities.project_api.create_project_for_rules(
            canonical, description, language
        )
        if result.get("ok") is not True:
            return result
        if self.fail_bind:
            return {"ok": False, "error": "fd_work_persistence_unconfirmed"}
        self.bind_project(result["project"]["id"], canonical)
        self.discard_case_selection(selection_token)
        result["fd_work_binding"] = {"bound": True, "verified": True}
        return result

    def rebind_project(
        self, project_id, name, description, language, selection_token
    ):
        canonical = self.validate_case_selection(selection_token, name)
        result = application_capabilities.project_api.update_project_for_rules(
            project_id, canonical, description, language
        )
        if result.get("ok") is not True:
            return result
        if self.fail_bind:
            return {"ok": False, "error": "fd_work_persistence_unconfirmed"}
        self.bind_project(project_id, canonical)
        self.discard_case_selection(selection_token)
        result["fd_work_binding"] = {"bound": True, "verified": True}
        return result

    def list_project_identities(self, projects):
        active_ids = self.list_bound_project_ids()
        return [
            {
                **dict(project),
                "external_identity_bound": project["id"] in active_ids,
            }
            for project in projects
        ]

    def clear_project_identity(self, project_id):
        try:
            self.clear_project_binding(project_id)
        except FDWorkEntryError as exc:
            return {"ok": False, "error": exc.code}
        return {"ok": True, "external_identity_binding": {"bound": False}}

    def after_project_deleted(self, project_id):
        self.clear_project_binding(project_id)
        return {"bound": False}


def _project_result(project_id, name):
    return {"ok": True, "project": {"id": project_id, "name": name}}


def _service(fd_work):
    identity = OptionalProjectIdentityCapability(
        external=fd_work,
        create_project=application_capabilities.project_api.create_project_for_rules,
        update_project=application_capabilities.project_api.update_project_for_rules,
        project_reader=application_capabilities.project_api.get_project,
    )
    return RulesApplicationService(project_identity=identity)


def test_enabled_plugin_keeps_local_creation_and_selected_case_binds(monkeypatch):
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *args: writes.append(args) or _project_result(len(writes), args[0]),
    )
    fd_work = _FDWork()
    service = _service(fd_work)

    plain = service.create_project_for_rules("Ordinary", "", "中文")
    selected = service.create_project_for_rules("CASE A", "", "中文", "token-a")

    assert plain["ok"] is True
    assert plain["external_identity_binding"] == {"bound": False}
    assert selected["ok"] is True
    assert selected["project"]["name"] == "CASE A"
    assert selected["external_identity_binding"] == {"bound": True, "verified": True}
    assert writes == [("Ordinary", "", "中文"), ("CASE A", "", "中文")]
    assert fd_work.bound == [(2, "CASE A")]
    assert fd_work.discarded == ["token-a"]


def test_bound_project_can_preserve_rename_to_local_or_rebind(monkeypatch):
    current = {"id": 7, "name": "CASE A"}
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "get_project",
        lambda _id: dict(current),
    )

    def update(project_id, name, description, language):
        writes.append((project_id, name, description, language))
        current["name"] = name
        return _project_result(project_id, name)

    monkeypatch.setattr(
        application_capabilities.project_api,
        "update_project_for_rules",
        update,
    )
    fd_work = _FDWork()
    service = _service(fd_work)

    unchanged = service.update_project_for_rules(
        7, "CASE A", "description", "中文"
    )
    renamed = service.update_project_for_rules(
        7, "Manual", "description", "中文"
    )
    rebound = service.update_project_for_rules(
        7, "CASE B", "description", "中文", "token-b"
    )

    assert unchanged["external_identity_binding"] == {"bound": True}
    assert renamed["ok"] is True
    assert renamed["project"]["name"] == "Manual"
    assert renamed["external_identity_binding"] == {"bound": False}
    assert fd_work.cleared == [7]
    assert rebound["project"]["name"] == "CASE B"
    assert rebound["external_identity_binding"] == {"bound": True, "verified": True}
    assert fd_work.bound == [(7, "CASE B")]


def test_unbound_project_can_rename_while_plugin_enabled(monkeypatch):
    current = {"id": 8, "name": "Local"}
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "get_project",
        lambda _id: dict(current),
    )

    def update(project_id, name, description, language):
        writes.append((project_id, name, description, language))
        current["name"] = name
        return _project_result(project_id, name)

    monkeypatch.setattr(
        application_capabilities.project_api,
        "update_project_for_rules",
        update,
    )
    fd_work = _FDWork()
    fd_work.bound_ids.clear()
    service = _service(fd_work)

    result = service.update_project_for_rules(
        8, "Renamed local", "description", "English"
    )

    assert result["ok"] is True
    assert result["external_identity_binding"] == {"bound": False}
    assert writes == [(8, "Renamed local", "description", "English")]
    assert fd_work.cleared == []


@pytest.mark.parametrize("token", ["expired", "mismatch"])
def test_invalid_selection_never_writes_or_binds(monkeypatch, token):
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *args: writes.append(args) or _project_result(1, args[0]),
    )
    fd_work = _FDWork()

    result = _service(fd_work).create_project_for_rules(
        "typed", "", "中文", token
    )

    assert result["ok"] is False
    assert writes == []
    assert fd_work.bound == []


def test_sidecar_failure_never_reports_partial_external_success(monkeypatch):
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *args: _project_result(9, args[0]),
    )
    fd_work = _FDWork(fail_bind=True)

    result = _service(fd_work).create_project_for_rules(
        "CASE A", "", "中文", "token-a"
    )

    assert result == {"ok": False, "error": "fd_work_persistence_unconfirmed"}


def test_bound_rename_succeeds_as_local_when_sidecar_cleanup_is_unavailable(monkeypatch):
    current = {"id": 7, "name": "CASE A"}
    monkeypatch.setattr(
        application_capabilities.project_api,
        "get_project",
        lambda _id: dict(current),
    )

    def update(project_id, name, description, language):
        current["name"] = name
        return _project_result(project_id, name)

    monkeypatch.setattr(
        application_capabilities.project_api,
        "update_project_for_rules",
        update,
    )
    fd_work = _FDWork(fail_clear=True)

    result = _service(fd_work).update_project_for_rules(
        7, "Manual", "", "中文"
    )

    assert result["ok"] is True
    assert result["external_identity_binding"]["bound"] is False
    assert "warning" in result["external_identity_binding"]
    assert current["name"] == "Manual"


def test_project_list_attaches_binding_truth_in_one_bulk_read(monkeypatch):
    projects = [
        {"id": 7, "name": "CASE A"},
        {"id": 8, "name": "Ordinary"},
    ]
    monkeypatch.setattr(
        application_capabilities.project_api,
        "list_project_bindings",
        lambda: projects,
    )
    fd_work = _FDWork()

    result = _service(fd_work).list_project_bindings()

    assert result == [
        {"id": 7, "name": "CASE A", "external_identity_bound": True},
        {"id": 8, "name": "Ordinary", "external_identity_bound": False},
    ]
    assert result is not projects
