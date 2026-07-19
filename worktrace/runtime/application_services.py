"""Explicit process composition root for bridge-facing application services."""
from __future__ import annotations

from ..api.app_api import ApplicationControlService
from ..api.application_services import ApplicationServices
from ..services import (
    database_maintenance_service,
    runtime_activity_state_service,
    secure_backup_service,
)
from .app_runtime import AppRuntime


def build_application_services(runtime: AppRuntime) -> ApplicationServices:
    return ApplicationServices(
        app_control=ApplicationControlService(runtime),
        runtime_view=runtime,
        maintenance=database_maintenance_service.MAINTENANCE_COORDINATOR,
        backup=secure_backup_service,
        runtime_state_provider=runtime_activity_state_service,
    )


__all__ = ["ApplicationServices", "build_application_services"]
