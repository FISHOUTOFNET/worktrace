"""Explicit process composition root for bridge-facing application services."""
from __future__ import annotations

from ..api.app_api import ApplicationControlService
from ..api.application_services import ApplicationServices
from ..services import database_maintenance_service
from .app_runtime import AppRuntime


def build_application_services(runtime: AppRuntime) -> ApplicationServices:
    maintenance = database_maintenance_service.MAINTENANCE_COORDINATOR
    return ApplicationServices(
        app_control=ApplicationControlService(runtime, maintenance),
        runtime_view=runtime,
    )


__all__ = ["ApplicationServices", "build_application_services"]
