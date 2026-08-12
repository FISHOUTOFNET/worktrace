from __future__ import annotations

from types import SimpleNamespace

from worktrace.webview_ui.bridge_timeline import TimelineBridgeMixin


class _TimelineCatalogStub:
    def list_selectable_projects(self):
        return [
            {
                "id": 1,
                "name": "未归类",
                "description": "",
                "last_used_at": None,
            },
            {
                "id": 2,
                "name": "26IP0165",
                "description": "Miragene",
                "last_used_at": "2026-08-12 15:30:00",
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


def test_timeline_project_catalog_exposes_last_used_at():
    bridge = TimelineBridgeMixin()
    bridge._services = SimpleNamespace(timeline=_TimelineCatalogStub())

    result = bridge.list_projects_for_timeline()

    assert result["ok"] is True
    assert result["editing_projects"][0]["last_used_at"] is None
    assert result["editing_projects"][1] == {
        "id": 2,
        "name": "26IP0165",
        "description": "Miragene",
        "last_used_at": "2026-08-12 15:30:00",
    }
    assert result["filter_projects"][0]["last_used_at"] == "2026-08-12 15:30:00"
