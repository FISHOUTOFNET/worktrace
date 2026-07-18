from __future__ import annotations

import ntpath
from typing import Protocol

from ..constants import ANCHOR_FILE_EXTENSIONS, STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED
from ..path_utils import looks_like_local_file_path
from ..platforms.base import ActiveWindow
from .browser_detector import BrowserDetector
from .email_detector import EmailDetector
from .ide_detector import IdeDetector
from .local_file_detector import LocalFileDetector
from .office_wps_detector import OfficeWpsDetector
from .resource_builders import make_system_resource
from .resource_helpers import (
    build_path_or_name_identity,
    display_name_from_path_or_name,
    normalize_for_key,
    resolve_file_candidate,
)
from .resource_policy import validate_resource_kind, validate_resource_subtype
from .types import DetectedResource


class ResourceDetector(Protocol):
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        ...


class SystemDetector:
    SYSTEM_PROCESS_NAMES = frozenset({"idle", "paused", "excluded", "error"})

    _PROCESS_TO_STATUS = {
        "idle": STATUS_IDLE,
        "paused": STATUS_PAUSED,
        "excluded": STATUS_EXCLUDED,
        "error": STATUS_ERROR,
    }

    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        process = (active_window.process_name or "").strip().lower()
        if process not in self.SYSTEM_PROCESS_NAMES:
            return None
        status = self._PROCESS_TO_STATUS[process]
        return make_system_resource(
            status,
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
        )


class FallbackFileDetector:
    """Detect anchor files from titles of unrecognized processes.

    When a process name is not recognized by any specific detector (e.g.
    ``word.exe`` instead of ``winword.exe``), this detector checks whether
    the window title or file_path_hint contains a file name with an anchor
    extension.  If so, it returns an anchor resource so that context carry
    and session merge work correctly.

    Only extensions in ``ANCHOR_FILE_EXTENSIONS`` are considered, so that
    context carry and session merge work correctly for anchor files.
    """

    _ANCHOR_EXT_SET = frozenset(ext.casefold() for ext in ANCHOR_FILE_EXTENSIONS)

    _EXT_TO_SUBTYPE: dict[str, str] = {
        ".docx": "word_document", ".doc": "word_document",
        ".xlsx": "spreadsheet", ".xls": "spreadsheet", ".csv": "csv_file",
        ".pptx": "presentation", ".ppt": "presentation",
        ".pdf": "pdf",
        ".txt": "text_file", ".md": "markdown_file",
    }

    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        file_path = resolve_file_candidate(
            active_window,
            allowed_extensions=self._ANCHOR_EXT_SET,
            prefer_hint=True,
            allow_title_path=True,
            allow_title_file=True,
        )
        if file_path is None:
            return None

        file_name = display_name_from_path_or_name(file_path)
        _, ext = ntpath.splitext(file_name)
        ext_lower = ext.casefold()
        if ext_lower not in self._ANCHOR_EXT_SET:
            return None

        return self._make_resource(active_window, file_path)

    def _make_resource(self, active_window: ActiveWindow, file_path: str) -> DetectedResource:
        file_name = display_name_from_path_or_name(file_path)
        _, ext = ntpath.splitext(file_name)
        subtype = self._EXT_TO_SUBTYPE.get(ext.casefold(), "text_file")

        identity_key = build_path_or_name_identity(file_path, "fallback_file", "fallback_file_name")
        path_hint = file_path if looks_like_local_file_path(file_path) else None

        return DetectedResource(
            resource_kind=validate_resource_kind("local_file"),
            resource_subtype=validate_resource_subtype(subtype),
            display_name=file_name,
            identity_key=identity_key,
            is_anchor=True,
            confidence=70,
            source="fallback_file_detector",
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
            path_hint=path_hint,
        )


class GenericAppDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        app_name = (active_window.app_name or "").strip()
        process_name = (active_window.process_name or "").strip()
        display_name = app_name or process_name or "未知应用"
        normalized = normalize_for_key(process_name)
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
        _default_registry.register(FallbackFileDetector())
        _default_registry.register(GenericAppDetector())
    return _default_registry


def detect_resource(active_window: ActiveWindow) -> DetectedResource:
    return _get_default_registry().detect(active_window)
