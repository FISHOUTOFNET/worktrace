"""Current-user Windows launch-at-login registration."""
from __future__ import annotations

import ntpath
import sys
from pathlib import Path
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "Trace"
LEGACY_RUN_VALUE_NAMES = ("WorkTrace",)
BACKGROUND_ARGUMENT = "--background"


class StartupRegistry(Protocol):
    def read_run_value(self, name: str) -> str | None: ...
    def write_run_value(self, name: str, value: str) -> None: ...
    def delete_run_value(self, name: str) -> None: ...


class WinregStartupRegistry:
    """Narrow HKCU registry adapter; never opens HKLM."""

    def read_run_value(self, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY,
                0,
                winreg.KEY_QUERY_VALUE,
            ) as key:
                value, value_type = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            return None
        return str(value)

    def write_run_value(self, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete_run_value(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


def installed_executable_path() -> Path | None:
    """Return the executable that may safely be registered for login startup."""

    if not sys.platform.startswith("win"):
        return None
    if not bool(getattr(sys, "frozen", False)):
        return None
    return Path(sys.executable).resolve()


class WindowsStartupRegistration:
    """Authoritative HKCU Run registration for the current executable."""

    def __init__(
        self,
        executable_path: Path | None = None,
        registry: StartupRegistry | None = None,
    ) -> None:
        self._executable_path = (
            Path(executable_path).resolve()
            if executable_path is not None
            else installed_executable_path()
        )
        self._registry = registry if registry is not None else WinregStartupRegistry()

    @property
    def supported(self) -> bool:
        return self._executable_path is not None and sys.platform.startswith("win")

    def expected_command(self) -> str:
        if self._executable_path is None:
            raise RuntimeError("launch_at_login_unsupported")
        return f'"{self._executable_path}" {BACKGROUND_ARGUMENT}'

    def _matches_expected(self, value: str | None) -> bool:
        if not isinstance(value, str):
            return False
        return ntpath.normcase(value.strip()) == ntpath.normcase(
            self.expected_command()
        )

    def is_configured(self) -> bool:
        if not self.supported:
            return False
        try:
            if self._matches_expected(self._registry.read_run_value(RUN_VALUE_NAME)):
                return True
            return any(
                self._matches_expected(self._registry.read_run_value(name))
                for name in LEGACY_RUN_VALUE_NAMES
            )
        except OSError:
            return False

    def enable(self, executable_path: Path | None = None) -> None:
        if executable_path is not None:
            self._executable_path = Path(executable_path).resolve()
        if not self.supported:
            raise RuntimeError("launch_at_login_unsupported")
        expected = self.expected_command()
        current = self._registry.read_run_value(RUN_VALUE_NAME)
        if not self._matches_expected(current):
            self._registry.write_run_value(RUN_VALUE_NAME, expected)
        for name in LEGACY_RUN_VALUE_NAMES:
            self._registry.delete_run_value(name)

    def disable(self) -> None:
        if not self.supported:
            raise RuntimeError("launch_at_login_unsupported")
        for name in (RUN_VALUE_NAME, *LEGACY_RUN_VALUE_NAMES):
            self._registry.delete_run_value(name)


__all__ = [
    "BACKGROUND_ARGUMENT",
    "LEGACY_RUN_VALUE_NAMES",
    "RUN_KEY",
    "RUN_VALUE_NAME",
    "WindowsStartupRegistration",
    "installed_executable_path",
]
