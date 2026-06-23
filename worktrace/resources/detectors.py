from __future__ import annotations

import re
from typing import Protocol

from ..platforms.base import ActiveWindow
from .browser_detector import BrowserDetector
from .email_detector import EmailDetector
from .ide_detector import IdeDetector
from .local_file_detector import LocalFileDetector
from .office_wps_detector import OfficeWpsDetector
from .resource_policy import validate_resource_kind, validate_resource_subtype
from .types import DetectedResource


class ResourceDetector(Protocol):
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        ...


class SystemDetector:
    SYSTEM_PROCESS_NAMES = frozenset({"idle", "paused", "excluded", "error"})

    SUBTYPE_MAP = {
        "idle": "idle",
        "paused": "paused",
        "excluded": "excluded",
        "error": "error",
    }

    DISPLAY_NAME_MAP = {
        "idle": "空闲",
        "paused": "已暂停",
        "excluded": "已排除",
        "error": "异常",
    }

    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        process = (active_window.process_name or "").strip().lower()
        if process not in self.SYSTEM_PROCESS_NAMES:
            return None
        subtype = self.SUBTYPE_MAP[process]
        display_name = self.DISPLAY_NAME_MAP.get(process, active_window.app_name or process)
        return DetectedResource(
            resource_kind=validate_resource_kind("system"),
            resource_subtype=validate_resource_subtype(subtype),
            display_name=display_name,
            identity_key=f"system:{subtype}",
            is_anchor=False,
            confidence=100,
            source="system_detector",
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
        )


class GenericAppDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        app_name = (active_window.app_name or "").strip()
        process_name = (active_window.process_name or "").strip()
        display_name = app_name or process_name or "未知应用"
        normalized = _normalize_process_name(process_name)
        return DetectedResource(
            resource_kind=validate_resource_kind("app"),
            resource_subtype=validate_resource_subtype("generic_app"),
            display_name=display_name,
            identity_key=f"app:{normalized}",
            is_anchor=False,
            confidence=50,
            source="generic_app_detector",
            app_name=app_name,
            process_name=process_name,
            window_title=active_window.window_title or "",
        )


class ResourceDetectorRegistry:
    def __init__(self) -> None:
        self._detectors: list[ResourceDetector] = []

    def register(self, detector: ResourceDetector) -> None:
        self._detectors.append(detector)

    def detect(self, active_window: ActiveWindow) -> DetectedResource:
        for detector in self._detectors:
            result = detector.detect(active_window)
            if result is not None:
                return result
        return _fallback_resource(active_window)


def _normalize_process_name(process_name: str) -> str:
    value = process_name.strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9._\-\u4e00-\u9fff]+", "-", value)
    return value.strip("-") or "unknown"


def _fallback_resource(active_window: ActiveWindow) -> DetectedResource:
    return DetectedResource(
        resource_kind="unknown",
        resource_subtype="unknown",
        display_name="未知资源",
        identity_key="unknown:unknown",
        is_anchor=False,
        confidence=0,
        source="fallback",
        app_name=active_window.app_name or "",
        process_name=active_window.process_name or "",
        window_title=active_window.window_title or "",
    )


_default_registry: ResourceDetectorRegistry | None = None


def _get_default_registry() -> ResourceDetectorRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ResourceDetectorRegistry()
        _default_registry.register(SystemDetector())
        _default_registry.register(OfficeWpsDetector())
        _default_registry.register(EmailDetector())
        _default_registry.register(IdeDetector())
        _default_registry.register(BrowserDetector())
        _default_registry.register(LocalFileDetector())
        _default_registry.register(GenericAppDetector())
    return _default_registry


def detect_resource(active_window: ActiveWindow) -> DetectedResource:
    return _get_default_registry().detect(active_window)
