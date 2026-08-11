"""One-shot installer bootstrap intents for current-user Windows installs."""
from __future__ import annotations

import logging
import sys
from typing import Any, Protocol

logger = logging.getLogger(__name__)

INSTALL_BOOTSTRAP_KEY = r"Software\WorkTrace\InstallBootstrap"
ENABLE_FD_WORK_VALUE = "EnableFDWork"


class FDWorkEnableCapability(Protocol):
    def set_enabled(self, enabled: bool) -> dict[str, object]: ...


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

    current_platform = sys.platform if platform is None else platform
    if not current_platform.startswith("win"):
        return False

    if registry is None:
        import winreg as registry

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
            try:
                registry.DeleteKey(registry.HKEY_CURRENT_USER, INSTALL_BOOTSTRAP_KEY)
            except FileNotFoundError:
                pass
            except OSError:
                # The key may contain future installer intents. Never delete them.
                pass
