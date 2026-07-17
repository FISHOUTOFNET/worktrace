"""Installation-scoped privacy consent and sensitive-runtime gate.

The privacy notice is an installation decision, not user business data. Backup
replacement and clear-all operations therefore preserve the accepted notice
version while still leaving collection paused. Every runtime capability that
can observe window, filesystem, or clipboard data must consult this service.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..constants import PRIVACY_NOTICE_VERSION
from ..db import get_connection, now_str
from .settings_service import (
    SettingMutationClass,
    clear_settings_cache,
    get_bool_setting,
    get_setting,
    set_settings,
)


class PrivacyGateRequiredError(PermissionError):
    """Raised when a sensitive runtime operation is attempted before consent."""


@dataclass(frozen=True)
class InstallationPrivacyState:
    legacy_accepted: bool
    accepted_version: str


def accepted_privacy_notice_version(*, conn=None) -> str:
    return str(get_setting("accepted_privacy_notice_version", "", conn=conn) or "")


def is_privacy_notice_accepted(*, conn=None) -> bool:
    version = accepted_privacy_notice_version(conn=conn)
    if version:
        return version == PRIVACY_NOTICE_VERSION
    legacy = get_bool_setting("first_run_notice_accepted", False, conn=conn)
    return bool(legacy and PRIVACY_NOTICE_VERSION == "1")


def accept_privacy_notice() -> None:
    set_settings(
        {
            "first_run_notice_accepted": "true",
            "accepted_privacy_notice_version": PRIVACY_NOTICE_VERSION,
        },
        mutation_class=SettingMutationClass.PRIVACY,
    )


def is_sensitive_runtime_allowed() -> bool:
    try:
        return is_privacy_notice_accepted()
    except Exception:
        return False


def require_sensitive_runtime_allowed() -> None:
    if not is_sensitive_runtime_allowed():
        raise PrivacyGateRequiredError("privacy_notice_required")


def capture_installation_privacy_state(*, conn=None) -> InstallationPrivacyState:
    return InstallationPrivacyState(
        legacy_accepted=get_bool_setting(
            "first_run_notice_accepted", False, conn=conn
        ),
        accepted_version=accepted_privacy_notice_version(conn=conn),
    )


def restore_installation_privacy_state(
    state: InstallationPrivacyState,
    *,
    conn=None,
) -> None:
    """Restore installation consent after replacing business data."""

    values = {
        "first_run_notice_accepted": (
            "true" if state.legacy_accepted else "false"
        ),
        "accepted_privacy_notice_version": state.accepted_version,
    }
    if conn is None:
        set_settings(values, mutation_class=SettingMutationClass.PRIVACY)
        return

    timestamp = now_str()
    for key, value in values.items():
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, timestamp),
        )
    clear_settings_cache("first_run_notice_accepted")
    clear_settings_cache("accepted_privacy_notice_version")


__all__ = [
    "InstallationPrivacyState",
    "PrivacyGateRequiredError",
    "accept_privacy_notice",
    "accepted_privacy_notice_version",
    "capture_installation_privacy_state",
    "is_privacy_notice_accepted",
    "is_sensitive_runtime_allowed",
    "require_sensitive_runtime_allowed",
    "restore_installation_privacy_state",
]
