"""Timeline application service decorated with optional project identity."""

from __future__ import annotations

from .application_capabilities import TimelineApplicationService
from .external_project_identity import ProjectIdentityIntegrationCapability


class ProjectIdentityTimelineApplicationService(TimelineApplicationService):
    """Attach generic external-identity state to the editable project catalog."""

    def __init__(
        self,
        project_identity: ProjectIdentityIntegrationCapability,
    ) -> None:
        self._project_identity = project_identity

    def list_selectable_projects(self):
        return self._project_identity.list_project_identities(
            super().list_selectable_projects()
        )


__all__ = ["ProjectIdentityTimelineApplicationService"]
