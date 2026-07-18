"""Installation-scoped privacy consent and sensitive-runtime gate.

The privacy notice is an installation decision, not user business data. Backup
replacement and clear-all operations therefore preserve the accepted notice
version while still leaving collection paused. Every runtime capability that
can observe window, filesystem, or clipboard data must consult this service.
"""

from __future__ import annotations

from ..constants import PRIVACY_NOTICE_VERSION
from .installation_metadata_store import (
    get_privacy_notice_version,
    set_privacy_notice_version,
)


class PrivacyGateRequiredError(PermissionError):
    """Raised when a sensitive runtime operation is attempted before consent."""


def accepted_privacy_notice_version() -> str:
    return get_privacy_notice_version()


def is_privacy_notice_accepted() -> bool:
    return accepted_privacy_notice_version() == PRIVACY_NOTICE_VERSION


def accept_privacy_notice() -> None:
    set_privacy_notice_version(PRIVACY_NOTICE_VERSION)


def is_sensitive_runtime_allowed() -> bool:
    try:
        return is_privacy_notice_accepted()
    except Exception:
        return False


def require_sensitive_runtime_allowed() -> None:
    if not is_sensitive_runtime_allowed():
        raise PrivacyGateRequiredError("privacy_notice_required")


__all__ = [
    "PrivacyGateRequiredError",
    "accept_privacy_notice",
    "accepted_privacy_notice_version",
    "is_privacy_notice_accepted",
    "is_sensitive_runtime_allowed",
    "require_sensitive_runtime_allowed",
]
