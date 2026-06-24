from __future__ import annotations

import ntpath
import re

from ..path_utils import looks_like_local_file_path
from ..platforms.base import ActiveWindow
from .resource_helpers import (
    build_path_or_name_identity,
    display_name_from_path_or_name,
    extract_file_name_from_title,
    normalize_for_key,
)
from .resource_policy import validate_resource_kind, validate_resource_subtype
from .types import DetectedResource

IDE_PROCESS_NAMES = frozenset({
    "code.exe", "code",
    "cursor.exe", "cursor",
    "pycharm64.exe", "pycharm64",
    "idea64.exe", "idea64",
    "webstorm64.exe", "webstorm64",
    "phpstorm64.exe", "phpstorm64",
    "rider64.exe", "rider64",
    "devenv.exe", "devenv",
    "sublime_text.exe", "sublime_text",
    "notepad++.exe", "notepad++",
})

IDE_CODE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".hpp",
    ".cs", ".php", ".rb", ".swift", ".kt", ".kts", ".sql",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".xml",
    ".html", ".css", ".scss", ".less", ".vue", ".svelte",
})


class IdeDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        process_lower = (active_window.process_name or "").strip().lower()
        if process_lower not in IDE_PROCESS_NAMES:
            return None

        # 1. Try file_path_hint or title for a code file
        hint = (active_window.file_path_hint or "").strip()
        title = (active_window.window_title or "").strip()

        code_file_path: str | None = None
        if hint:
            _, ext = ntpath.splitext(hint)
            if ext.casefold() in IDE_CODE_EXTENSIONS:
                code_file_path = hint
            else:
                # hint present but not a code extension; still trust it as a
                # full path if it looks like one, so title-based detection can
                # try next.
                pass

        if code_file_path is None:
            file_name = extract_file_name_from_title(title)
            if file_name:
                _, ext = ntpath.splitext(file_name)
                if ext.casefold() in IDE_CODE_EXTENSIONS:
                    # Prefer a full path from hint when available, else the
                    # bare file name from the title.
                    code_file_path = hint if hint and looks_like_local_file_path(hint) else file_name

        if code_file_path:
            return self._make_code_file_resource(active_window, code_file_path)

        # 2. Try to identify workspace/project from title
        workspace = self._extract_workspace(title, process_lower)
        if workspace:
            return self._make_workspace_resource(active_window, workspace)

        # 3. No file or workspace identified - let GenericAppDetector handle it
        return None

    def _make_code_file_resource(self, active_window: ActiveWindow, file_path: str) -> DetectedResource:
        file_name = display_name_from_path_or_name(file_path)
        identity_key = build_path_or_name_identity(file_path, "ide_file", "ide_file_name")

        return DetectedResource(
            resource_kind=validate_resource_kind("ide_file"),
            resource_subtype=validate_resource_subtype("code_file"),
            display_name=file_name,
            identity_key=identity_key,
            is_anchor=True,
            confidence=85,
            source="ide_detector",
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
            path_hint=file_path if looks_like_local_file_path(file_path) else None,
        )

    def _make_workspace_resource(self, active_window: ActiveWindow, workspace: str) -> DetectedResource:
        process_lower = (active_window.process_name or "").strip().lower()
        normalized_ws = normalize_for_key(workspace)
        identity_key = f"ide_workspace:{process_lower}:{normalized_ws}"

        return DetectedResource(
            resource_kind=validate_resource_kind("ide_file"),
            resource_subtype=validate_resource_subtype("ide_workspace"),
            display_name=workspace,
            identity_key=identity_key,
            is_anchor=True,
            confidence=60,
            source="ide_detector",
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
        )

    _IDE_NAME_PATTERNS = re.compile(
        r"^(Visual Studio Code|VS Code|Code|PyCharm|IntelliJ IDEA|WebStorm|PhpStorm|Rider|Visual Studio|Sublime Text|Notepad\+\+|Cursor)$",
        re.IGNORECASE,
    )

    def _extract_workspace(self, title: str, process_lower: str) -> str | None:
        if not title:
            return None
        # VS Code: "file.py - MyProject - Visual Studio Code"
        # PyCharm: "file.py – MyProject – PyCharm"
        # PyCharm (no file): "MyProject – PyCharm"
        # IntelliJ: "file.java – MyProject – IntelliJ IDEA"
        # Remove IDE name suffix first
        cleaned = re.sub(
            r"\s*[-–—]\s*(Visual Studio Code|VS Code|PyCharm|IntelliJ IDEA|WebStorm|PhpStorm|Rider|Visual Studio|Sublime Text|Notepad\+\+|Cursor).*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
        if not cleaned:
            return None
        # If the cleaned title is just an IDE name, it's not a workspace
        if self._IDE_NAME_PATTERNS.match(cleaned):
            return None
        # Split by " - " or " – " and take the last segment as workspace
        parts = re.split(r"\s*[-–—]\s*", cleaned)
        if len(parts) >= 2:
            # Last part before IDE name is likely workspace
            candidate = parts[-1].strip()
            if candidate and len(candidate) >= 2 and not self._IDE_NAME_PATTERNS.match(candidate):
                return candidate
        elif len(parts) == 1:
            # Only one segment (e.g., "MyProject" after removing "– PyCharm")
            candidate = parts[0].strip()
            if candidate and len(candidate) >= 2 and not self._IDE_NAME_PATTERNS.match(candidate):
                return candidate
        return None
