"""Explicit API-facing capabilities injected into the WebView bridge."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .app_api import ApplicationRuntimeCapability
from .application_capabilities import (
    BackupCapability,
    FDWorkCapability,
    OverviewCapability,
    ProjectCatalogCapability,
    RulesCapability,
    SettingsCapability,
    StatisticsCapability,
    TimelineCapability,
)


class ApplicationControlCapability(Protocol):
    def get_collection_status(self) -> dict[str, Any]: ...
    def toggle_collection(self) -> dict[str, Any]: ...
    def accept_privacy_notice_and_start(self) -> dict[str, Any]: ...
    def set_clipboard_capture_policy(self, enabled: bool) -> dict[str, Any]: ...
    def request_shutdown(self) -> None: ...


@dataclass(frozen=True)
class ApplicationServices:
    """Bridge composition containing only consumed capabilities."""

    app_control: ApplicationControlCapability
    runtime_view: ApplicationRuntimeCapability
    overview: OverviewCapability
    settings: SettingsCapability
    backup: BackupCapability
    statistics: StatisticsCapability
    projects: ProjectCatalogCapability
    timeline: TimelineCapability
    fd_work: FDWorkCapability
    rules: RulesCapability


__all__ = ["ApplicationServices"]
