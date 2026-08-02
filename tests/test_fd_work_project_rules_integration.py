from __future__ import annotations

import pytest

from worktrace.api import application_capabilities
from worktrace.api.application_capabilities import RulesApplicationService
from worktrace.integrations.fd_work.contracts import FDWorkEntryError


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _FDWork:
    def __init__(self, enabled=True, *, fail_bind=False):
        self.enabled = enabled
        self.fail_bind = fail_bind
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
        self.cleared.append(project_id)
        self.bound_ids.discard(project_id)

    def list_bound_project_ids(self):
        return set(self.bound_ids)


def _project_result(project_id, name):
    return {"ok": True, "project": {"id": project_id, "name": name}}


def test_enabled_create_allows_free_text_and_selected_case_binds(monkeypatch):
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *args: writes.append(args) or _project_result(len(writes), args[0]),
    )
    fd_work = _FDWork()
    service = RulesApplicationService(fd_work=fd_work)

    plain = service.create_project_for_rules("Ordinary", "", "中文")
    selected = service.create_project_for_rules("typed fragment", "", "中文", "token-a")

    assert plain["ok"] is True
    assert plain["fd_work_binding"]["bound"] is False
    assert selected["ok"] is True
    assert selected["project"]["name"] == "CASE A"
    assert selected["fd_work_binding"]["bound"] is True
    assert writes == [("Ordinary", "", "中文"), ("CASE A", "", "中文")]
    assert fd_work.bound == [(2, "CASE A")]
    assert fd_work.discarded == ["token-a"]


def test_update_preserves_rebinds_or_clears_from_explicit_facts(monkeypatch):
    current = {"id": 7, "name": "CASE A"}
    writes = []
    monkeypatch.setattr(application_capabilities.project_api, "get_project", lambda _id: dict(current))

    def update(project_id, name, description, language):
        writes.append((project_id, name, description, language))
        current["name"] = name
        return _project_result(project_id, name)

    monkeypatch.setattr(application_capabilities.project_api, "update_project_for_rules", update)
    fd_work = _FDWork()
    service = RulesApplicationService(fd_work=fd_work)

    unchanged = service.update_project_for_rules(7, "CASE A", "new description", "中文")
    renamed = service.update_project_for_rules(7, "Manual", "new description", "中文")
    rebound = service.update_project_for_rules(7, "ignored", "new description", "中文", "token-b")

    assert unchanged["fd_work_binding"]["bound"] is True
    assert fd_work.cleared == [7]
    assert renamed["fd_work_binding"]["bound"] is False
    assert rebound["project"]["name"] == "CASE B"
    assert rebound["fd_work_binding"]["bound"] is True
    assert fd_work.bound == [(7, "CASE B")]


@pytest.mark.parametrize("token", ["expired", "mismatch"])
def test_invalid_selection_never_writes_or_binds(monkeypatch, token):
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *args: writes.append(args) or _project_result(1, args[0]),
    )
    fd_work = _FDWork()

    result = RulesApplicationService(fd_work=fd_work).create_project_for_rules(
        "typed", "", "中文", token
    )

    assert result["ok"] is False
    assert writes == []
    assert fd_work.bound == []


def test_sidecar_failure_is_partial_success_and_fail_closed(monkeypatch):
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *args: _project_result(9, args[0]),
    )
    fd_work = _FDWork(fail_bind=True)

    result = RulesApplicationService(fd_work=fd_work).create_project_for_rules(
        "typed", "", "中文", "token-a"
    )

    assert result["ok"] is True
    assert result["project"]["name"] == "CASE A"
    assert result["fd_work_binding"] == {
        "bound": False,
        "warning": "项目已保存，但关联 FD Work 失败，请重新关联",
    }
    assert fd_work.cleared == [9]
    assert fd_work.discarded == ["token-a"]


def test_delete_clears_binding_only_after_project_delete_succeeds(monkeypatch):
    fd_work = _FDWork()
    monkeypatch.setattr(
        application_capabilities.project_api,
        "delete_project_for_rules",
        lambda project_id: _project_result(project_id, "CASE A"),
    )

    result = RulesApplicationService(fd_work=fd_work).delete_project_for_rules(7)

    assert result["ok"] is True
    assert fd_work.cleared == [7]


def test_project_list_attaches_bindings_in_one_bulk_read(monkeypatch):
    projects = [{"id": 7, "name": "CASE A"}, {"id": 8, "name": "Ordinary"}]
    monkeypatch.setattr(application_capabilities.project_api, "list_project_bindings", lambda: projects)
    fd_work = _FDWork()

    result = RulesApplicationService(fd_work=fd_work).list_project_bindings()

    assert result == [
        {"id": 7, "name": "CASE A", "fd_work_bound": True},
        {"id": 8, "name": "Ordinary", "fd_work_bound": False},
    ]
    assert result is not projects
