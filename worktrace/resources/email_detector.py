from __future__ import annotations

import ntpath
import re

from ..path_utils import (
    extract_file_path_from_title,
    looks_like_local_file_path,
)
from ..platforms.base import ActiveWindow
from .resource_helpers import (
    build_path_or_name_identity,
    display_name_from_path_or_name,
    normalize_for_key,
)
from .resource_policy import validate_resource_kind, validate_resource_subtype
from .types import DetectedResource

EMAIL_PROCESS_NAMES = frozenset({
    "outlook.exe", "outlook",
    "thunderbird.exe", "thunderbird",
    "hxoutlook.exe", "hxoutlook",
    "olk.exe", "olk",
    "mail.exe", "mail",
})

EMAIL_FILE_EXTENSIONS = frozenset({".eml", ".msg"})


_EMAIL_FILE_NAME_RE = re.compile(
    r"(?P<name>[^\\/:*?\"<>|\r\n]+?\.(?:eml|msg))(?=$|[\s\"'）)\]】。；;，,]| - | [-–—])",
    re.IGNORECASE,
)


def _extract_email_file_name_from_title(window_title: str | None) -> str | None:
    """Extract an .eml/.msg file name from a window title.

    Returns the bare file name (e.g. ``通知.eml``) without the surrounding
    ``- Outlook`` suffix. Returns ``None`` if no email file name is found.
    """
    title = (window_title or "").strip()
    if not title:
        return None
    matches = list(_EMAIL_FILE_NAME_RE.finditer(title))
    if not matches:
        return None
    raw = matches[-1].group("name").strip()
    cleaned = raw.strip(" -—–_|[]()（）")
    return cleaned or None


class EmailDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        process_lower = (active_window.process_name or "").strip().lower()
        is_email_process = process_lower in EMAIL_PROCESS_NAMES

        # Check for email file extensions
        hint = (active_window.file_path_hint or "").strip()
        title = active_window.window_title or ""

        email_file_path = None
        if hint:
            _, ext = ntpath.splitext(hint)
            if ext.casefold() in EMAIL_FILE_EXTENSIONS:
                email_file_path = hint

        # Also try to extract an .eml/.msg file name from the window title.
        # Outlook/Thunderbird often show "通知.eml - Outlook" without a full
        # path; we should still identify this as an email_file rather than
        # degrading to email_message.
        email_file_name_from_title: str | None = None
        if not email_file_path:
            email_file_name_from_title = _extract_email_file_name_from_title(title)
            if email_file_name_from_title:
                # If the title also contains a full path, prefer that.
                title_path = extract_file_path_from_title(title)
                if title_path and looks_like_local_file_path(title_path):
                    _, ext = ntpath.splitext(title_path)
                    if ext.casefold() in EMAIL_FILE_EXTENSIONS:
                        email_file_path = title_path

        if not email_file_path and not email_file_name_from_title and not is_email_process:
            return None

        # .eml/.msg file -> email_file (path or name-only)
        if email_file_path:
            return self._make_email_file_resource(active_window, email_file_path)
        if email_file_name_from_title:
            return self._make_email_file_resource(active_window, email_file_name_from_title)

        # Email process without file -> email_message
        if is_email_process:
            return self._make_email_message_resource(active_window)

        return None

    def _make_email_file_resource(self, active_window: ActiveWindow, file_path: str) -> DetectedResource:
        file_name = display_name_from_path_or_name(file_path)
        identity_key = build_path_or_name_identity(file_path, "email_file", "email_file_name")
        path_hint = file_path if looks_like_local_file_path(file_path) else None

        return DetectedResource(
            resource_kind=validate_resource_kind("email"),
            resource_subtype=validate_resource_subtype("email_file"),
            display_name=file_name,
            identity_key=identity_key,
            is_anchor=True,
            confidence=85,
            source="email_detector",
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
            path_hint=path_hint,
        )

    def _make_email_message_resource(self, active_window: ActiveWindow) -> DetectedResource:
        title = (active_window.window_title or "").strip()
        subject = self._extract_subject(title)
        display_name = subject or title or active_window.app_name or "邮件"
        process_name = (active_window.process_name or "").strip()

        normalized_subject = normalize_for_key(subject or display_name)
        normalized_process = normalize_for_key(process_name)
        identity_key = f"email_subject:{normalized_subject}|{normalized_process}"

        return DetectedResource(
            resource_kind=validate_resource_kind("email"),
            resource_subtype=validate_resource_subtype("email_message"),
            display_name=display_name,
            identity_key=identity_key,
            is_anchor=True,
            confidence=80,
            source="email_detector",
            app_name=active_window.app_name or "",
            process_name=process_name,
            window_title=active_window.window_title or "",
        )

    def _extract_subject(self, window_title: str) -> str:
        if not window_title:
            return ""
        # Outlook pattern: "Subject - Outlook" or "Subject - Message (HTML) - Outlook"
        # Thunderbird pattern: "Subject - Mozilla Thunderbird"
        # Remove common suffixes
        cleaned = re.sub(
            r"\s*[-–—]\s*(Outlook|Microsoft Outlook|Mozilla Thunderbird|Mail).*$",
            "",
            window_title,
            flags=re.IGNORECASE,
        )
        # Remove status indicators like "(HTML)", "(Plain Text)", etc.
        cleaned = re.sub(r"\s*\((?:HTML|Plain\s*Text|RTF)\)\s*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()
