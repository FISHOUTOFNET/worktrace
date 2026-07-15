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
from .settings_service import clear_settings_cache, get_bool_setting, get_setting, set_setting


class PrivacyGateRequiredError(PermissionError):
    """Raised when a sensitive runtime operation is attempted before consent."""


@dataclass(frozen=True)
class InstallationPrivacyState:
    legacy_accepted: bool
    accepted_version: str


def accepted_privacy_notice_version(*, conn=None) -> str:
    return str(get_setting("accepted_privacy_notice_version", "", conn=conn) or "")


def is_privacy_notice_accepted(*, conn=None) -> bool:
    """Return whether this installation accepted the current notice version.

    Existing installations that only carry the legacy boolean remain accepted;
    the next explicit acceptance writes the versioned key as well.
    """

    version = accepted_privacy_notice_version(conn=conn)
    if version:
        return version == PRIVACY_NOTICE_VERSION
    return get_bool_setting("first_run_notice_accepted", False, conn=conn)


def accept_privacy_notice() -> None:
    set_setting("first_run_notice_accepted", "true")
    set_setting("accepted_privacy_notice_version", PRIVACY_NOTICE_VERSION)
    clear_settings_cache("first_run_notice_accepted")
    clear_settings_cache("accepted_privacy_notice_version")


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

    def _restore(connection) -> None:
        timestamp = now_str()
        values = {
            "first_run_notice_accepted": (
                "true" if state.legacy_accepted else "false"
            ),
            "accepted_privacy_notice_version": state.accepted_version,
        }
        for key, value in values.items():
            connection.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, timestamp),
            )

    if conn is not None:
        _restore(conn)
        return
    with get_connection() as own_conn:
        _restore(own_conn)
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
