"""Explicit API-facing capabilities injected into the WebView bridge."""
from __future__ import annotations

from dataclasses import dataclass

from .app_api import ApplicationControlService, ApplicationRuntimeCapability


@dataclass(frozen=True)
class ApplicationServices:
    """Minimal bridge composition containing only consumed capabilities."""

    app_control: ApplicationControlService
    runtime_view: ApplicationRuntimeCapability


__all__ = ["ApplicationServices"]
