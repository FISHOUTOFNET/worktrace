from __future__ import annotations

import ntpath

from ..path_utils import looks_like_local_file_path, split_file_path
from ..platforms.base import ActiveWindow
from .resource_helpers import (
    build_path_or_name_identity,
    display_name_from_path_or_name,
    resolve_file_candidate,
)
from .resource_policy import validate_resource_kind, validate_resource_subtype
from .types import DetectedResource

OFFICE_WPS_PROCESS_NAMES = frozenset({
    "winword.exe", "winword",
    "excel.exe", "excel",
    "powerpnt.exe", "powerpnt",
    "wps.exe", "wps",
    "et.exe", "et",
    "wpp.exe", "wpp",
    "kwps.exe", "kwps",
    "ket.exe", "ket",
    "kwpp.exe", "kwpp",
})

_EXT_TO_SUBTYPE: dict[str, str] = {
    ".doc": "word_document",
    ".docx": "word_document",
    ".xls": "spreadsheet",
    ".xlsx": "spreadsheet",
    ".csv": "spreadsheet",
    ".ppt": "presentation",
    ".pptx": "presentation",
    ".pdf": "pdf",
    ".txt": "text_file",
    ".md": "markdown_file",
}

_ALLOWED_EXTENSIONS = frozenset(_EXT_TO_SUBTYPE.keys())


class OfficeWpsDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        process_lower = (active_window.process_name or "").strip().lower()
        if process_lower not in OFFICE_WPS_PROCESS_NAMES:
            return None

        file_path = resolve_file_candidate(
            active_window,
            allowed_extensions=_ALLOWED_EXTENSIONS,
            prefer_hint=True,
            allow_title_path=True,
            allow_title_file=True,
            use_folder_index=True,
        )
        if file_path is None:
            return None

        file_name = display_name_from_path_or_name(file_path)
        _, ext = ntpath.splitext(file_name)
        subtype = _EXT_TO_SUBTYPE.get(ext.casefold(), "unknown")

        identity_key = build_path_or_name_identity(file_path, "office_file", "office_file_name")

        return DetectedResource(
            resource_kind=validate_resource_kind("office_document"),
            resource_subtype=validate_resource_subtype(subtype),
            display_name=file_name,
            identity_key=identity_key,
            is_anchor=True,
            confidence=90,
            source="office_wps_detector",
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
            path_hint=file_path if looks_like_local_file_path(file_path) else None,
        )
