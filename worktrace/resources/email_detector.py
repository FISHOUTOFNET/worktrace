from __future__ import annotations

import ntpath
import re

from ..activity_identity import extract_file_name_from_title, normalize_file_name
from ..path_utils import (
    looks_like_local_file_path,
    normalize_path_key,
    split_file_path,
)
from ..platforms.base import ActiveWindow
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

        if not email_file_path and not is_email_process:
            return None

        # .eml/.msg file -> email_file
        if email_file_path:
            return self._make_email_file_resource(active_window, email_file_path)

        # Email process without file -> email_message
        if is_email_process:
            return self._make_email_message_resource(active_window)

        return None

    @staticmethod
    def is_email_metadata_capture_enabled() -> bool:
        """Check if deep email metadata capture is enabled. Default: False."""
        try:
            from ..services.settings_service import get_setting
            return get_setting("email_metadata_capture_enabled", "false").lower() == "true"
        except Exception:
            return False

    def _make_email_file_resource(self, active_window: ActiveWindow, file_path: str) -> DetectedResource:
        full_path, parent_dir, file_stem = split_file_path(file_path)
        file_name = ntpath.basename(full_path)

        if looks_like_local_file_path(full_path):
            identity_key = f"email_file:{normalize_path_key(full_path)}"
        else:
            identity_key = f"email_file_name:{normalize_file_name(file_name)}"

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
            path_hint=full_path if looks_like_local_file_path(full_path) else None,
        )

    def _make_email_message_resource(self, active_window: ActiveWindow) -> DetectedResource:
        title = (active_window.window_title or "").strip()
        subject = self._extract_subject(title)
        display_name = subject or title or active_window.app_name or "邮件"
        process_name = (active_window.process_name or "").strip()

        normalized_subject = _normalize_for_key(subject or display_name)
        normalized_process = _normalize_for_key(process_name)
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


def _normalize_for_key(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9._\-\u4e00-\u9fff@]+", "-", value)
    return value.strip("-") or "unknown"
