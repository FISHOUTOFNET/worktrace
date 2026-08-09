from __future__ import annotations

from types import SimpleNamespace

import pytest

from worktrace.api import application_capabilities
from worktrace.api.external_project_identity import OptionalProjectIdentityCapability
from worktrace.api.project_identity_timeline import ProjectIdentityTimelineApplicationService
from worktrace.webview_ui.bridge_project_identity_timeline import (
    ProjectIdentityTimelineBridgeMixin,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _ExternalIdentity:
    def __init__(self, bound_ids=()):
        self.bound_ids = set(bound_ids)

    def list_bound_project_ids(self):
        return set(self.bound_ids)

    def create_bound_project(self, *args):
        raise AssertionError(args)

    def rebind_project(self, *args):
        raise AssertionError(args)

    def clear_project_identity(self, project_id):
        return {"ok": True, "external_identity_binding": {"bound": False}}

    def after_project_deleted(self, project_id):
        return {"bound": False}


def _identity(external):
    return OptionalProjectIdentityCapability(
        external=external,
        create_project=lambda name, description, language: {
            "ok": True,
            "project": {"id": 1, "name": name},
        },
        update_project=lambda project_id, name, description, language: {
            "ok": True,
            "project": {"id": project_id, "name": name},
        },
        project_reader=lambda project_id: {"id": project_id, "name": "Local"},
    )


def test_timeline_service_reads_binding_state_through_generic_identity_capability(
    monkeypatch,
):
    monkeypatch.setattr(
        application_capabilities.project_api,
        "list_selectable_projects",
        lambda: [
            {"id": 7, "name": "CASE A", "description": ""},
            {"id": 8, "name": "Local", "description": ""},
        ],
    )
    service = ProjectIdentityTimelineApplicationService(
        _identity(_ExternalIdentity({7}))
    )

    result = service.list_selectable_projects()

    assert result[0]["external_identity_bound"] is True
    assert result[1]["external_identity_bound"] is False


def test_durable_binding_truth_does_not_depend_on_plugin_runtime_state():
    external = _ExternalIdentity({7})
    identity = _identity(external)

    result = identity.list_project_identities(
        [
            {"id": 7, "name": "CASE A"},
            {"id": 8, "name": "Local"},
        ]
    )

    assert result == [
        {"id": 7, "name": "CASE A", "external_identity_bound": True},
        {"id": 8, "name": "Local", "external_identity_bound": False},
    ]


def test_timeline_bridge_exposes_binding_only_on_editing_catalog():
    class _Timeline:
        def list_selectable_projects(self):
            return [
                {
                    "id": 7,
                    "name": "CASE A",
                    "description": "",
                    "external_identity_bound": True,
                },
                {
                    "id": 8,
                    "name": "Local",
                    "description": "",
                    "external_identity_bound": False,
                },
            ]

        def list_filter_projects(self):
            return [
                {"id": 7, "name": "CASE A", "description": ""},
                {"id": 8, "name": "Local", "description": ""},
            ]

    bridge = ProjectIdentityTimelineBridgeMixin()
    bridge._services = SimpleNamespace(timeline=_Timeline())

    result = bridge.list_projects_for_timeline()

    assert result["ok"] is True
    assert result["editing_projects"] == [
        {
            "id": 7,
            "name": "CASE A",
            "description": "",
            "fd_work_bound": True,
        },
        {
            "id": 8,
            "name": "Local",
            "description": "",
            "fd_work_bound": False,
        },
    ]
    assert all("fd_work_bound" not in item for item in result["filter_projects"])
