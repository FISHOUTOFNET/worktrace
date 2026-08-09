"""Timeline bridge projection that exposes generic project identity state."""

from __future__ import annotations

import logging
from typing import Any

from .bridge_timeline import TimelineBridgeMixin

logger = logging.getLogger(__name__)


class ProjectIdentityTimelineBridgeMixin(TimelineBridgeMixin):
    """Expose optional external identity only on the editable project catalog."""

    def list_projects_for_timeline(self) -> dict[str, Any]:
        try:
            editing_projects = self._services.timeline.list_selectable_projects()
            filter_projects = self._services.timeline.list_filter_projects()
            editing_dto = [
                {
                    "id": int(project.get("id") or 0),
                    "name": str(project.get("name") or ""),
                    "description": str(project.get("description") or ""),
                    "fd_work_bound": (
                        project.get("external_identity_bound") is True
                    ),
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
                "projects": editing_dto,
                "editing_projects": editing_dto,
                "filter_projects": filter_dto,
            }
        except Exception:
            logger.exception("webview bridge list_projects_for_timeline failed")
            return {
                "ok": False,
                "error": "operation_failed",
                "message": "操作失败",
            }


__all__ = ["ProjectIdentityTimelineBridgeMixin"]
