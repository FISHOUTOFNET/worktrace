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

_LOCAL_FILE_EXTENSIONS = frozenset({
    ".pdf", ".txt", ".md", ".csv",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".hpp",
    ".cs", ".php", ".rb", ".swift", ".kt", ".kts", ".sql",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".xml",
    ".html", ".css", ".scss", ".less", ".vue", ".svelte",
    ".rst", ".tex",
})

_CODE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".hpp",
    ".cs", ".php", ".rb", ".swift", ".kt", ".kts", ".sql",
    ".vue", ".svelte",
})

_EXT_TO_SUBTYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".txt": "text_file",
    ".md": "markdown_file",
    ".csv": "csv_file",
}


class LocalFileDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        file_path = self._resolve_file_path(active_window)
        if file_path is None:
            return None

        full_path, parent_dir, file_stem = split_file_path(file_path)
        file_name = ntpath.basename(full_path)
        _, ext = ntpath.splitext(file_name)
        ext_lower = ext.casefold()

        if ext_lower not in _LOCAL_FILE_EXTENSIONS:
            return None

        subtype = _EXT_TO_SUBTYPE.get(ext_lower)
        if subtype is None:
            subtype = "code_file" if ext_lower in _CODE_EXTENSIONS else "text_file"

        if looks_like_local_file_path(full_path):
            identity_key = f"file_path:{normalize_path_key(full_path)}"
        else:
            identity_key = f"file_name:{normalize_file_name(file_name)}"

        return DetectedResource(
            resource_kind=validate_resource_kind("local_file"),
            resource_subtype=validate_resource_subtype(subtype),
            display_name=file_name,
            identity_key=identity_key,
            is_anchor=True,
            confidence=80,
            source="local_file_detector",
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
            if ext.casefold() in _LOCAL_FILE_EXTENSIONS:
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
