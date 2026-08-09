"""Shared project catalog bridge.

The catalog is a cross-page capability consumed by Timeline, Statistics and
Project Rules. It is intentionally separate from every page-specific bridge.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ProjectCatalogBridgeMixin:
    def list_project_catalog(self) -> dict[str, Any]:
        try:
            editing_projects = self._services.projects.list_editing_projects()
            filter_projects = self._services.projects.list_filter_projects()
            editing_dto = [
                {
                    "id": int(project.get("id") or 0),
                    "name": str(project.get("name") or ""),
                    "description": str(project.get("description") or ""),
                    "fd_work_bound": project.get("external_identity_bound") is True,
                }
                for project in editing_projects
            ]
            filter_dto = [
                {
                    "id": int(project.get("id") or 0),
                    "name": str(project.get("name") or ""),
                    "description": str(project.get("description") or ""),
                }
                for project in filter_projects
            ]
            return {
                "ok": True,
                "editing_projects": editing_dto,
                "filter_projects": filter_dto,
            }
        except Exception:
            logger.exception("webview bridge list_project_catalog failed")
            return {"ok": False, "error": "operation_failed", "message": "操作失败"}

    def list_projects_for_timeline(self) -> dict[str, Any]:
        """Temporary frontend migration alias; catalog ownership stays here."""
        return self.list_project_catalog()


__all__ = ["ProjectCatalogBridgeMixin"]
