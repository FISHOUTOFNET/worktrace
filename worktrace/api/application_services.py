"""Explicit API-facing capabilities injected into the WebView bridge."""
from __future__ import annotations

from dataclasses import dataclass

from .app_api import ApplicationControlService, ApplicationRuntimeCapability
from .application_capabilities import (
    BackupCapability,
    OverviewCapability,
    RulesCapability,
    SettingsCapability,
    StatisticsCapability,
    TimelineCapability,
)


@dataclass(frozen=True)
class ApplicationServices:
    """Bridge composition containing only consumed capabilities."""

    app_control: ApplicationControlService
    runtime_view: ApplicationRuntimeCapability
    overview: OverviewCapability
    settings: SettingsCapability
    backup: BackupCapability
    statistics: StatisticsCapability
    timeline: TimelineCapability
    rules: RulesCapability


__all__ = ["ApplicationServices"]
