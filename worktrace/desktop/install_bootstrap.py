"""One-shot installer bootstrap intents for current-user Windows installs."""
from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any, Protocol

from worktrace.privacy_policy import PRIVACY_NOTICE_VERSION

logger = logging.getLogger(__name__)

INSTALL_BOOTSTRAP_KEY = r"Software\WorkTrace\InstallBootstrap"
ENABLE_FD_WORK_VALUE = "EnableFDWork"
PRIVACY_NOTICE_VALUE = "PrivacyNoticeVersion"
PENDING_PRIVACY_NOTICE_VALUE = "PendingPrivacyNoticeVersion"


class FDWorkEnableCapability(Protocol):
    def set_enabled(self, enabled: bool) -> dict[str, object]: ...


def _current_registry(*, registry: Any | None, platform: str | None) -> Any | None:
    current_platform = sys.platform if platform is None else platform
    if not current_platform.startswith("win"):
        return None
    if registry is not None:
        return registry

    import winreg

    return winreg


def _delete_bootstrap_key_if_empty(registry: Any) -> None:
    try:
        registry.DeleteKey(registry.HKEY_CURRENT_USER, INSTALL_BOOTSTRAP_KEY)
    except FileNotFoundError:
        pass
    except OSError:
        # The key can contain another installer intent or durable installer marker.
        pass


def consume_privacy_install_intent(
    *,
    accept_notice: Callable[[str], bool] | None = None,
    registry: Any | None = None,
    platform: str | None = None,
) -> bool:
    """Persist installer-confirmed privacy acceptance through application storage.

    Setup writes only a transient HKCU marker. The application validates the
    requested version against its own shipped policy constant before asking the
    privacy service to persist acceptance in installation metadata. Transient
    persistence failures leave the marker intact so the next normal launch can
    retry; stale or otherwise invalid versions are discarded.
    """

    registry = _current_registry(registry=registry, platform=platform)
    if registry is None:
        return False

    try:
        key = registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            INSTALL_BOOTSTRAP_KEY,
            0,
            registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE,
        )
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("installer bootstrap registry key unavailable", exc_info=True)
        return False

    delete_key_after_close = False
    try:
        try:
            value, _value_type = registry.QueryValueEx(
                key,
                PENDING_PRIVACY_NOTICE_VALUE,
            )
        except FileNotFoundError:
            return False
        except OSError:
            logger.warning("installer privacy intent unreadable", exc_info=True)
            return False

        requested_version = str(value).strip()
        if requested_version != PRIVACY_NOTICE_VERSION:
            logger.warning(
                "discarding installer privacy intent version=%r current=%r",
                requested_version,
                PRIVACY_NOTICE_VERSION,
            )
            try:
                registry.DeleteValue(key, PENDING_PRIVACY_NOTICE_VALUE)
                delete_key_after_close = True
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning(
                    "invalid installer privacy intent cleanup failed",
                    exc_info=True,
                )
            return False

        if accept_notice is None:
            from worktrace.services.privacy_gate_service import (
                accept_privacy_notice_version,
            )

            accept_notice = accept_privacy_notice_version

        try:
            accepted = bool(accept_notice(requested_version))
        except Exception:
            logger.exception("installer privacy intent could not be persisted")
            return False
        if not accepted:
            logger.error("installer privacy intent was not accepted by privacy service")
            return False

        try:
            registry.DeleteValue(key, PENDING_PRIVACY_NOTICE_VALUE)
            delete_key_after_close = True
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("consumed installer privacy intent cleanup failed", exc_info=True)
        return True
    finally:
        registry.CloseKey(key)
        if delete_key_after_close:
            _delete_bootstrap_key_if_empty(registry)


def consume_fd_work_install_intent(
    fd_work: FDWorkEnableCapability,
    *,
    registry: Any | None = None,
    platform: str | None = None,
) -> bool:
    """Enable FD Work once when the installer explicitly requested it.

    The installer owns only a transient HKCU intent. The application capability
    remains authoritative for durable plugin settings and privacy-gated runtime
    behavior. The intent is deleted only after the capability confirms that the
    enabled state was persisted, so a transient settings failure is retryable on
    the next launch.
    """

    registry = _current_registry(registry=registry, platform=platform)
    if registry is None:
        return False

    try:
        key = registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            INSTALL_BOOTSTRAP_KEY,
            0,
            registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE,
        )
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("installer bootstrap registry key unavailable", exc_info=True)
        return False

    delete_key_after_close = False
    try:
        try:
            value, _value_type = registry.QueryValueEx(key, ENABLE_FD_WORK_VALUE)
        except FileNotFoundError:
            return False
        except OSError:
            logger.warning("installer FD Work intent unreadable", exc_info=True)
            return False

        requested = value is True or value == 1 or (
            isinstance(value, str) and value.strip() == "1"
        )
        if not requested:
            try:
                registry.DeleteValue(key, ENABLE_FD_WORK_VALUE)
                delete_key_after_close = True
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("invalid installer FD Work intent cleanup failed", exc_info=True)
            return False

        try:
            status = fd_work.set_enabled(True)
        except Exception:
            logger.exception("installer FD Work intent could not be persisted")
            return False
        if not isinstance(status, dict) or status.get("enabled") is not True:
            logger.error("installer FD Work intent was not confirmed by capability")
            return False

        try:
            registry.DeleteValue(key, ENABLE_FD_WORK_VALUE)
            delete_key_after_close = True
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("consumed installer FD Work intent cleanup failed", exc_info=True)
        return True
    finally:
        registry.CloseKey(key)
        if delete_key_after_close:
            _delete_bootstrap_key_if_empty(registry)
