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

# Version 2 was briefly used by an unpublished build while the policy text was
# being centralized. It must not invalidate an existing version-1 acceptance,
# and it must not survive as a future acceptance for a genuinely published v2.
_UNPUBLISHED_NOTICE_VERSION = "2"


class PrivacyGateRequiredError(PermissionError):
    """Raised when a sensitive runtime operation is attempted before consent."""


def accepted_privacy_notice_version() -> str:
    return get_privacy_notice_version()


def is_privacy_notice_accepted() -> bool:
    accepted_version = accepted_privacy_notice_version()
    if accepted_version == PRIVACY_NOTICE_VERSION:
        return True
    if (
        PRIVACY_NOTICE_VERSION == "1"
        and accepted_version == _UNPUBLISHED_NOTICE_VERSION
    ):
        # Normalize the unpublished marker immediately so a future, genuinely
        # published v2 still requires a fresh acceptance.
        set_privacy_notice_version(PRIVACY_NOTICE_VERSION)
        return True
    return False


def accept_privacy_notice_version(version: str) -> bool:
    """Persist acceptance only when ``version`` is the policy shipped now.

    This narrow entry point is used by trusted interactive installer bootstrap
    code. Rejecting stale/future versions prevents an installer or script from
    bypassing a newly required privacy notice.
    """

    if str(version or "").strip() != PRIVACY_NOTICE_VERSION:
        return False
    set_privacy_notice_version(PRIVACY_NOTICE_VERSION)
    return True


def accept_privacy_notice() -> None:
    if not accept_privacy_notice_version(PRIVACY_NOTICE_VERSION):
        raise RuntimeError("privacy_notice_version_mismatch")


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
    "accept_privacy_notice_version",
    "accepted_privacy_notice_version",
    "is_privacy_notice_accepted",
    "is_sensitive_runtime_allowed",
    "require_sensitive_runtime_allowed",
]
