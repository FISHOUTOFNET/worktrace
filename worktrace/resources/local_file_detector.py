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
from .title_parsing import extract_probable_file_name
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

# Office document extensions are owned by OfficeWpsDetector / FallbackFileDetector
# with dedicated subtypes; LocalFileDetector defers them to preserve those subtypes.
_OFFICE_DOCUMENT_EXTENSIONS = frozenset({
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
})


class LocalFileDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        file_path = resolve_file_candidate(
            active_window,
            allowed_extensions=_LOCAL_FILE_EXTENSIONS,
            prefer_hint=True,
            allow_title_path=True,
            allow_title_file=True,
        )
        probable_title_file = False
        if file_path is None:
            file_path = extract_probable_file_name(active_window.window_title)
            probable_title_file = file_path is not None
        if file_path is None:
            return None

        file_name = display_name_from_path_or_name(file_path)
        _, ext = ntpath.splitext(file_name)
        ext_lower = ext.casefold()
        is_full_local_path = looks_like_local_file_path(file_path)

        # Dedicated Office/WPS/Fallback detectors own these extensions even when
        # only a bare title file name is available.
        if ext_lower in _OFFICE_DOCUMENT_EXTENSIONS:
            return None

        subtype = _EXT_TO_SUBTYPE.get(ext_lower)
        if subtype is None:
            if ext_lower in _CODE_EXTENSIONS:
                subtype = "code_file"
            elif ext_lower in _LOCAL_FILE_EXTENSIONS:
                # Whitelisted extension without a dedicated subtype
                # (e.g. .json, .yaml, .html).
                subtype = "text_file"
            else:
                # A full local path is authoritative regardless of extension.
                # A conservative probable-title candidate is lower-confidence
                # evidence, but still enough to preserve file identity instead
                # of degrading to the host application process.
                if not is_full_local_path and not probable_title_file:
                    return None
                subtype = "unknown"

        identity_key = build_path_or_name_identity(file_path, "file_path", "file_name")

        return DetectedResource(
            resource_kind=validate_resource_kind("local_file"),
            resource_subtype=validate_resource_subtype(subtype),
            display_name=file_name,
            identity_key=identity_key,
            is_anchor=True,
            confidence=65 if probable_title_file and not is_full_local_path else 80,
            source="local_file_detector",
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
            path_hint=file_path if is_full_local_path else None,
        )
