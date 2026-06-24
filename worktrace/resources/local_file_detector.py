from __future__ import annotations

import ntpath

from ..path_utils import looks_like_local_file_path
from ..platforms.base import ActiveWindow
from .resource_helpers import (
    build_path_or_name_identity,
    display_name_from_path_or_name,
    resolve_file_candidate,
)
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
        file_path = resolve_file_candidate(
            active_window,
            allowed_extensions=_LOCAL_FILE_EXTENSIONS,
            prefer_hint=True,
            allow_title_path=True,
            allow_title_file=True,
            use_folder_index=True,
        )
        if file_path is None:
            return None

        file_name = display_name_from_path_or_name(file_path)
        _, ext = ntpath.splitext(file_name)
        ext_lower = ext.casefold()

        if ext_lower not in _LOCAL_FILE_EXTENSIONS:
            return None

        subtype = _EXT_TO_SUBTYPE.get(ext_lower)
        if subtype is None:
            subtype = "code_file" if ext_lower in _CODE_EXTENSIONS else "text_file"

        identity_key = build_path_or_name_identity(file_path, "file_path", "file_name")

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
            path_hint=file_path if looks_like_local_file_path(file_path) else None,
        )
