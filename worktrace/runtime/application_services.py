"""Composition root for production application-service capabilities."""
from __future__ import annotations

from ..api.app_api import ApplicationControlService
from ..api.application_capabilities import (
    BackupApplicationService,
    OverviewApplicationService,
    ProjectCatalogApplicationService,
    RulesApplicationService,
    SettingsApplicationService,
    TimelineApplicationService,
)
from ..api.application_lifecycle import ApplicationDataLifecycle
from ..api.application_services import ApplicationServices
from ..api.external_project_identity import (
    IntegratingProjectIdentityCapability,
    LocalProjectIdentityCapability,
)
from ..api import project_api
from ..integrations.fd_work.project_identity import FDWorkProjectIdentityIntegration
from ..integrations.fd_work.service import FDWorkService
from .statistics_application_service import RealtimeStatisticsApplicationService


def build_application_services(runtime, maintenance, *, desktop_shell=None) -> ApplicationServices:
    """Build the explicit application-service dependency graph for the desktop app."""
    fd_work = FDWorkService()
    data_lifecycle = ApplicationDataLifecycle((fd_work,))
    local_identity = LocalProjectIdentityCapability(
        create_project=project_api.create_project_for_rules,
        update_project=project_api.update_project_for_rules,
    )
    project_identity = IntegratingProjectIdentityCapability(
        local_identity,
        FDWorkProjectIdentityIntegration(fd_work),
    )
    return ApplicationServices(
        app_control=ApplicationControlService(
            runtime,
            maintenance,
            desktop_shell=desktop_shell,
        ),
        runtime_view=runtime,
        overview=OverviewApplicationService(),
        settings=SettingsApplicationService(data_lifecycle=data_lifecycle),
        backup=BackupApplicationService(data_lifecycle),
        statistics=RealtimeStatisticsApplicationService(),
        projects=ProjectCatalogApplicationService(project_identity=project_identity),
        timeline=TimelineApplicationService(),
        fd_work=fd_work,
        rules=RulesApplicationService(project_identity=project_identity),
    )


__all__ = ["build_application_services"]
