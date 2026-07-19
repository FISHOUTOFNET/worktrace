"""Explicit process composition root for bridge-facing application services."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..services import (
    database_maintenance_service,
    runtime_activity_state_service,
    secure_backup_service,
)
from .app_runtime import AppRuntime


@dataclass(frozen=True)
class ApplicationServices:
    runtime: AppRuntime
    maintenance: database_maintenance_service.RuntimeMaintenanceCoordinator
    backup: Any
    runtime_state_provider: Any


def build_application_services(runtime: AppRuntime) -> ApplicationServices:
    return ApplicationServices(
        runtime=runtime,
        maintenance=database_maintenance_service.MAINTENANCE_COORDINATOR,
        backup=secure_backup_service,
        runtime_state_provider=runtime_activity_state_service,
    )


__all__ = ["ApplicationServices", "build_application_services"]
