"""Explicit API-facing capabilities injected into the WebView bridge."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .app_api import ApplicationControlService, ApplicationRuntimeCapability


@dataclass(frozen=True)
class ApplicationServices:
    """Concrete bridge composition without backend implementation imports."""

    app_control: ApplicationControlService
    runtime_view: ApplicationRuntimeCapability
    maintenance: Any
    backup: Any
    runtime_state_provider: Any


__all__ = ["ApplicationServices"]
