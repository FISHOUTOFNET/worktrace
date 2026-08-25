"""Current-user Windows launch-at-login registration."""
from __future__ import annotations

import ntpath
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "WorkTrace"
BACKGROUND_ARGUMENT = "--background"
TASK_NAME = "WorkTrace Launch At Login"

_TASK_TRIGGER_LOGON = 9
_TASK_ACTION_EXEC = 0
_TASK_CREATE_OR_UPDATE = 6
_TASK_LOGON_INTERACTIVE_TOKEN = 3
_TASK_RUNLEVEL_LUA = 0
_TASK_INSTANCES_IGNORE_NEW = 2


@dataclass(frozen=True)
class StartupTaskSpec:
    executable_path: Path
    arguments: str
    working_directory: Path


class StartupRegistry(Protocol):
    def read_run_value(self, name: str) -> str | None: ...
    def delete_run_value(self, name: str) -> None: ...


class StartupTaskScheduler(Protocol):
    def exists(self, name: str) -> bool: ...
    def is_configured(self, name: str, spec: StartupTaskSpec) -> bool: ...
    def register(self, name: str, spec: StartupTaskSpec) -> None: ...
    def delete(self, name: str) -> None: ...


class WinregStartupRegistry:
    """Narrow HKCU compatibility adapter for the retired Run registration."""

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


def _normalized_windows_path(value: object) -> str:
    return ntpath.normcase(ntpath.normpath(str(value or "").strip().strip('"')))


def _current_user_sid() -> str:
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return str(win32security.ConvertSidToStringSid(sid))
    finally:
        token.Close()


class WindowsTaskScheduler:
    """Narrow current-user Task Scheduler adapter."""

    def _root_folder(self):
        import win32com.client

        service = win32com.client.Dispatch("Schedule.Service")
        service.Connect()
        return service, service.GetFolder("\\")

    def _get_task(self, name: str):
        _service, root = self._root_folder()
        try:
            return root.GetTask(name)
        except Exception as exc:
            hresult = getattr(exc, "hresult", None)
            if hresult in (-2147024894, -2147024893):
                return None
            # Dynamic COM errors also expose the HRESULT in args[0].
            args = getattr(exc, "args", ())
            if args and args[0] in (-2147024894, -2147024893):
                return None
            raise

    def exists(self, name: str) -> bool:
        return self._get_task(name) is not None

    def is_configured(self, name: str, spec: StartupTaskSpec) -> bool:
        task = self._get_task(name)
        if task is None or not bool(task.Enabled):
            return False
        definition = task.Definition
        actions = definition.Actions
        triggers = definition.Triggers
        if int(actions.Count) != 1 or int(triggers.Count) != 1:
            return False

        action = actions.Item(1)
        trigger = triggers.Item(1)
        settings = definition.Settings
        principal = definition.Principal
        return all(
            (
                int(action.Type) == _TASK_ACTION_EXEC,
                _normalized_windows_path(action.Path)
                == _normalized_windows_path(spec.executable_path),
                str(action.Arguments or "").strip() == spec.arguments,
                _normalized_windows_path(action.WorkingDirectory)
                == _normalized_windows_path(spec.working_directory),
                int(trigger.Type) == _TASK_TRIGGER_LOGON,
                bool(trigger.Enabled),
                int(principal.LogonType) == _TASK_LOGON_INTERACTIVE_TOKEN,
                int(principal.RunLevel) == _TASK_RUNLEVEL_LUA,
                bool(settings.Enabled),
                bool(settings.StartWhenAvailable),
                not bool(settings.DisallowStartIfOnBatteries),
                not bool(settings.StopIfGoingOnBatteries),
                str(settings.ExecutionTimeLimit or "").upper() == "PT0S",
                int(settings.MultipleInstances) == _TASK_INSTANCES_IGNORE_NEW,
            )
        )

    def register(self, name: str, spec: StartupTaskSpec) -> None:
        service, root = self._root_folder()
        definition = service.NewTask(0)
        definition.RegistrationInfo.Description = (
            "Launch WorkTrace in background when the current user signs in."
        )

        user_sid = _current_user_sid()
        principal = definition.Principal
        principal.UserId = user_sid
        principal.LogonType = _TASK_LOGON_INTERACTIVE_TOKEN
        principal.RunLevel = _TASK_RUNLEVEL_LUA

        trigger = definition.Triggers.Create(_TASK_TRIGGER_LOGON)
        trigger.Id = "CurrentUserLogon"
        trigger.UserId = user_sid
        trigger.Delay = "PT0S"
        trigger.Enabled = True

        action = definition.Actions.Create(_TASK_ACTION_EXEC)
        action.Path = str(spec.executable_path)
        action.Arguments = spec.arguments
        action.WorkingDirectory = str(spec.working_directory)

        settings = definition.Settings
        settings.Enabled = True
        settings.StartWhenAvailable = True
        settings.DisallowStartIfOnBatteries = False
        settings.StopIfGoingOnBatteries = False
        settings.ExecutionTimeLimit = "PT0S"
        settings.MultipleInstances = _TASK_INSTANCES_IGNORE_NEW

        root.RegisterTaskDefinition(
            name,
            definition,
            _TASK_CREATE_OR_UPDATE,
            user_sid,
            "",
            _TASK_LOGON_INTERACTIVE_TOKEN,
        )

    def delete(self, name: str) -> None:
        _service, root = self._root_folder()
        try:
            root.DeleteTask(name, 0)
        except Exception as exc:
            hresult = getattr(exc, "hresult", None)
            args = getattr(exc, "args", ())
            if hresult in (-2147024894, -2147024893) or (
                args and args[0] in (-2147024894, -2147024893)
            ):
                return
            raise


def installed_executable_path() -> Path | None:
    """Return the executable that may safely be registered for login startup."""

    if not sys.platform.startswith("win"):
        return None
    if not bool(getattr(sys, "frozen", False)):
        return None
    return Path(sys.executable).resolve()


class WindowsStartupRegistration:
    """Authoritative current-user Task Scheduler launch-at-login registration."""

    def __init__(
        self,
        executable_path: Path | None = None,
        registry: StartupRegistry | None = None,
        scheduler: StartupTaskScheduler | None = None,
    ) -> None:
        self._executable_path = (
            Path(executable_path).resolve()
            if executable_path is not None
            else installed_executable_path()
        )
        self._registry = registry if registry is not None else WinregStartupRegistry()
        self._scheduler = scheduler if scheduler is not None else WindowsTaskScheduler()

    @property
    def supported(self) -> bool:
        return self._executable_path is not None and sys.platform.startswith("win")

    def expected_command(self) -> str:
        if self._executable_path is None:
            raise RuntimeError("launch_at_login_unsupported")
        return f'"{self._executable_path}" {BACKGROUND_ARGUMENT}'

    def _task_spec(self) -> StartupTaskSpec:
        if self._executable_path is None:
            raise RuntimeError("launch_at_login_unsupported")
        return StartupTaskSpec(
            executable_path=self._executable_path,
            arguments=BACKGROUND_ARGUMENT,
            working_directory=self._executable_path.parent,
        )

    def _legacy_value(self) -> str | None:
        return self._registry.read_run_value(RUN_VALUE_NAME)

    def _legacy_is_configured(self) -> bool:
        try:
            value = self._legacy_value()
        except OSError:
            return False
        if not isinstance(value, str):
            return False
        return ntpath.normcase(value.strip()) == ntpath.normcase(self.expected_command())

    def is_configured(self) -> bool:
        if not self.supported:
            return False
        try:
            if self._scheduler.is_configured(TASK_NAME, self._task_spec()):
                return True
        except Exception:
            pass
        return self._legacy_is_configured()

    def enable(self, executable_path: Path | None = None) -> None:
        if executable_path is not None:
            self._executable_path = Path(executable_path).resolve()
        if not self.supported:
            raise RuntimeError("launch_at_login_unsupported")

        spec = self._task_spec()
        if not self._scheduler.is_configured(TASK_NAME, spec):
            self._scheduler.register(TASK_NAME, spec)
        if not self._scheduler.is_configured(TASK_NAME, spec):
            raise OSError("launch_at_login_task_verification_failed")

        # Delete the retired Run entry only after the scheduled task is verified,
        # so a registration failure cannot silently remove a working startup path.
        self._registry.delete_run_value(RUN_VALUE_NAME)

    def migrate_legacy_registration(self) -> None:
        if not self.supported:
            raise RuntimeError("launch_at_login_unsupported")

        task_exists = self._scheduler.exists(TASK_NAME)
        legacy_value = self._legacy_value()
        legacy_enabled = isinstance(legacy_value, str) and bool(legacy_value.strip())
        if not task_exists and not legacy_enabled:
            return
        self.enable()

    def disable(self) -> None:
        if not self.supported:
            raise RuntimeError("launch_at_login_unsupported")

        first_error: Exception | None = None
        try:
            self._scheduler.delete(TASK_NAME)
        except Exception as exc:
            first_error = exc
        try:
            self._registry.delete_run_value(RUN_VALUE_NAME)
        except Exception as exc:
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise first_error


__all__ = [
    "BACKGROUND_ARGUMENT",
    "RUN_KEY",
    "RUN_VALUE_NAME",
    "TASK_NAME",
    "StartupTaskSpec",
    "WindowsStartupRegistration",
    "WindowsTaskScheduler",
    "installed_executable_path",
]
