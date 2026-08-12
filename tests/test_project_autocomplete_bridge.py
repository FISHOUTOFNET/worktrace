from __future__ import annotations

from types import SimpleNamespace

import pytest

from worktrace.webview_ui.bridge_projects import ProjectCatalogBridgeMixin


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _ProjectCatalogStub:
    def list_editing_projects(self):
        return [
            {
                "id": 1,
                "name": "未归类",
                "description": "",
                "last_used_at": None,
                "external_identity_bound": False,
            },
            {
                "id": 2,
                "name": "26IP0165",
                "description": "Miragene",
                "last_used_at": "2026-08-12 15:30:00",
                "external_identity_bound": True,
            },
        ]

    def list_filter_projects(self):
        return [
            {
                "id": 2,
                "name": "26IP0165",
                "description": "Miragene",
                "last_used_at": "2026-08-12 15:30:00",
            }
        ]


def test_shared_project_catalog_exposes_last_used_at_without_losing_binding_state():
    bridge = ProjectCatalogBridgeMixin()
    bridge._services = SimpleNamespace(projects=_ProjectCatalogStub())

    result = bridge.list_project_catalog()

    assert result["ok"] is True
    assert result["editing_projects"][0]["last_used_at"] is None
    assert result["editing_projects"][1] == {
        "id": 2,
        "name": "26IP0165",
        "description": "Miragene",
        "last_used_at": "2026-08-12 15:30:00",
        "fd_work_bound": True,
    }
    assert result["filter_projects"][0]["last_used_at"] == "2026-08-12 15:30:00"
    assert "fd_work_bound" not in result["filter_projects"][0]
