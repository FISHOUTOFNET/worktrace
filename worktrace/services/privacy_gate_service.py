from __future__ import annotations

from .settings_service import get_bool_setting, get_setting, set_setting

PRIVACY_NOTICE_VERSION = "1"
_ACCEPTED_VERSION_KEY = "accepted_privacy_notice_version"
_LEGACY_ACCEPTED_KEY = "first_run_notice_accepted"


def accepted_notice_version() -> str:
    """Return the installation-level accepted notice version."""
    value = str(get_setting(_ACCEPTED_VERSION_KEY, "") or "")
    if value:
        return value
    if get_bool_setting(_LEGACY_ACCEPTED_KEY, False):
        return PRIVACY_NOTICE_VERSION
    return ""


def is_privacy_notice_accepted() -> bool:
    return accepted_notice_version() == PRIVACY_NOTICE_VERSION


def accept_current_privacy_notice() -> None:
    """Persist acceptance for the current installation and notice version."""
    set_setting(_ACCEPTED_VERSION_KEY, PRIVACY_NOTICE_VERSION)
    # Keep the legacy key during the v0.x transition so older read paths fail
    # closed rather than unexpectedly reopening the gate.
    set_setting(_LEGACY_ACCEPTED_KEY, "true")


def restore_installation_consent(version: str) -> None:
    """Restore installation consent after a database replacement."""
    if str(version or "") == PRIVACY_NOTICE_VERSION:
        accept_current_privacy_notice()


def is_sensitive_runtime_allowed() -> bool:
    """Single policy used by collector, folder indexing, and clipboard capture."""
    return is_privacy_notice_accepted()


def require_sensitive_runtime_allowed() -> None:
    if not is_sensitive_runtime_allowed():
        raise PermissionError("privacy_notice_required")
