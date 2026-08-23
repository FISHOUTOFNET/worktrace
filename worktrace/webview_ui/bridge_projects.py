"""Shared project catalog bridge.

The catalog is a cross-page capability consumed by Timeline, Statistics and
Project Rules. It is intentionally separate from every page-specific bridge.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _project_catalog_dto(project: dict[str, Any], *, include_binding: bool) -> dict[str, Any]:
    dto: dict[str, Any] = {
        "id": int(project.get("id") or 0),
        "name": str(project.get("name") or ""),
        "description": str(project.get("description") or ""),
    }
    if include_binding:
        dto["fd_work_bound"] = project.get("external_identity_bound") is True
    return dto


def _project_last_used_projection(projects: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(int(project.get("id") or 0)): str(project.get("last_used_at") or "")
        for project in projects
        if int(project.get("id") or 0) > 0 and project.get("last_used_at")
    }


class ProjectCatalogBridgeMixin:
    def list_project_catalog(self) -> dict[str, Any]:
        try:
            editing_projects = self._services.projects.list_editing_projects()
            filter_projects = self._services.projects.list_filter_projects()
            editing_dto = [
                _project_catalog_dto(project, include_binding=True)
                for project in editing_projects
            ]
            filter_dto = [
                _project_catalog_dto(project, include_binding=False)
                for project in filter_projects
            ]
            return {
                "ok": True,
                "editing_projects": editing_dto,
                "filter_projects": filter_dto,
                "project_last_used_at": _project_last_used_projection(editing_projects),
            }
        except Exception:
            logger.exception("webview bridge list_project_catalog failed")
            return {"ok": False, "error": "operation_failed", "message": "操作失败"}

    def list_projects_for_timeline(self) -> dict[str, Any]:
        """Temporary frontend migration alias; catalog ownership stays here."""
        return self.list_project_catalog()


__all__ = ["ProjectCatalogBridgeMixin"]
