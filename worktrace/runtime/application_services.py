"""Explicit process composition root for bridge-facing application services."""
from __future__ import annotations

from ..api.app_api import ApplicationControlService
from ..api.application_lifecycle import ApplicationDataLifecycle
from ..api.application_capabilities import (
    BackupApplicationService,
    OverviewApplicationService,
    ProjectCatalogApplicationService,
    RulesApplicationService,
    SettingsApplicationService,
    StatisticsApplicationService,
    TimelineApplicationService,
)
from ..api.application_services import ApplicationServices
from ..api.external_project_identity import OptionalProjectIdentityCapability
from ..services import database_maintenance_service
from ..services import project_service
from ..api import project_api
from ..integrations.fd_work.binding_repository import FDWorkBindingRepository
from ..integrations.fd_work.binding_service import FDWorkBindingService
from ..integrations.fd_work.draft_builder import FDWorkEntryDraftBuilder
from ..integrations.fd_work.integration_service import FDWorkIntegrationService
from .app_runtime import AppRuntime
from .post_privacy_startup import PostPrivacyStartupCoordinator


def build_application_services(
    runtime: AppRuntime,
    *,
    fd_work_interaction_coordinator=None,
    paths=None,
) -> ApplicationServices:
    maintenance = database_maintenance_service.MAINTENANCE_COORDINATOR
    app_paths = paths if paths is not None else runtime.paths
    binding_repository = FDWorkBindingRepository(
        app_paths.base_dir / "plugins" / "fd_work" / "state.db"
    )
    binding_service = FDWorkBindingService(
        binding_repository,
        project_reader=project_api.get_project,
        project_list_reader=project_service.list_user_project_identities,
    )
    binding_service.start_pending_reconciliation()
    fd_work = FDWorkIntegrationService(
        draft_builder=FDWorkEntryDraftBuilder(binding_verifier=binding_service),
        binding_service=binding_service,
        interaction_coordinator=fd_work_interaction_coordinator,
        project_creator=project_api.create_project_for_rules,
        project_updater=project_api.update_project_for_rules,
        project_reader=project_api.get_project,
    )
    project_identity = OptionalProjectIdentityCapability(
        external=fd_work,
        create_project=project_api.create_project_for_rules,
        update_project=project_api.update_project_for_rules,
        project_reader=project_api.get_project,
    )
    data_lifecycle = ApplicationDataLifecycle((fd_work,))
    base_app_control = ApplicationControlService(runtime, maintenance)
    app_control = PostPrivacyStartupCoordinator(
        base_app_control,
        participants=(fd_work, runtime.collector_supervisor),
    )
    return ApplicationServices(
        app_control=app_control,
        runtime_view=runtime,
        overview=OverviewApplicationService(),
        settings=SettingsApplicationService(data_lifecycle=data_lifecycle),
        backup=BackupApplicationService(data_lifecycle),
        statistics=StatisticsApplicationService(),
        projects=ProjectCatalogApplicationService(project_identity),
        timeline=TimelineApplicationService(),
        fd_work=fd_work,
        rules=RulesApplicationService(project_identity=project_identity),
    )


__all__ = ["ApplicationServices", "build_application_services"]
