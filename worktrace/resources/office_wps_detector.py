from __future__ import annotations

import ntpath

from ..activity_identity import extract_file_name_from_title, normalize_file_name
from ..path_utils import (
    extract_file_path_from_title,
    looks_like_local_file_path,
    normalize_path_key,
    split_file_path,
)
from ..platforms.base import ActiveWindow
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


class OfficeWpsDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        process_lower = (active_window.process_name or "").strip().lower()
        if process_lower not in OFFICE_WPS_PROCESS_NAMES:
            return None

        file_path = self._resolve_file_path(active_window)
        if file_path is None:
            return None

        full_path, parent_dir, file_stem = split_file_path(file_path)
        file_name = ntpath.basename(full_path)
        _, ext = ntpath.splitext(file_name)
        subtype = _EXT_TO_SUBTYPE.get(ext.casefold(), "unknown")

        if looks_like_local_file_path(full_path):
            identity_key = f"office_file:{normalize_path_key(full_path)}"
        else:
            identity_key = f"office_file_name:{normalize_file_name(file_name)}"

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
            path_hint=full_path if looks_like_local_file_path(full_path) else None,
        )

    def _resolve_file_path(self, active_window: ActiveWindow) -> str | None:
        # 1. Prefer file_path_hint
        hint = active_window.file_path_hint
        if hint and hint.strip():
            if looks_like_local_file_path(hint):
                return hint
            # file_path_hint might be a bare file name
            return hint

        # 2. Extract full path from window title
        title = active_window.window_title or ""
        title_path = extract_file_path_from_title(title)
        if title_path:
            return title_path

        # 3. Extract file name from title
        file_name = extract_file_name_from_title(title)
        if file_name:
            _, ext = ntpath.splitext(file_name)
            if ext.casefold() in _EXT_TO_SUBTYPE:
                # Try folder index lookup
                indexed = self._resolve_indexed_path(title)
                if indexed:
                    return indexed
                return file_name

        return None

    def _resolve_indexed_path(self, window_title: str | None) -> str | None:
        try:
            from ..services.folder_index_service import resolve_unique_path_from_title
            return resolve_unique_path_from_title(window_title, include_excluded=True)
        except Exception:
            return None
