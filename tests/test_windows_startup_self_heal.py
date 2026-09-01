from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import worktrace.platforms.windows_startup as windows_startup
from worktrace.platforms.windows_startup import (
    BACKGROUND_ARGUMENT,
    TASK_NAME,
    StartupTaskSpec,
    WindowsStartupRegistration,
    WindowsTaskScheduler,
)


class FakeRegistry:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.deletes = 0

    def read_run_value(self, name: str) -> str | None:
        assert name == "WorkTrace"
        return self.value

    def delete_run_value(self, name: str) -> None:
        assert name == "WorkTrace"
        self.deletes += 1
        self.value = None


class FakeScheduler:
    def __init__(self, *, exists: bool = False, configured: bool = False) -> None:
        self.task_exists = exists
        self.configured = configured
        self.registered: list[tuple[str, StartupTaskSpec]] = []
        self.fail_register = False

    def exists(self, name: str) -> bool:
        assert name == TASK_NAME
        return self.task_exists

    def is_configured(self, name: str, spec: StartupTaskSpec) -> bool:
        assert name == TASK_NAME
        return self.task_exists and self.configured

    def register(self, name: str, spec: StartupTaskSpec) -> None:
        assert name == TASK_NAME
        self.registered.append((name, spec))
        if self.fail_register:
            raise OSError("scheduler denied")
        self.task_exists = True
        self.configured = True

    def delete(self, name: str) -> None:
        assert name == TASK_NAME
        self.task_exists = False
        self.configured = False


def _registration(
    monkeypatch,
    tmp_path: Path,
    *,
    registry: FakeRegistry,
    scheduler: FakeScheduler,
) -> WindowsStartupRegistration:
    monkeypatch.setattr(sys, "platform", "win32")
    return WindowsStartupRegistration(
        executable_path=tmp_path / "Trace.exe",
        registry=registry,
        scheduler=scheduler,
    )


def test_repair_does_not_create_launch_intent_for_disabled_user(
    monkeypatch, tmp_path
) -> None:
    registry = FakeRegistry()
    scheduler = FakeScheduler()
    registration = _registration(
        monkeypatch,
        tmp_path,
        registry=registry,
        scheduler=scheduler,
    )

    assert registration.repair_if_needed() == "disabled"
    assert scheduler.registered == []
    assert registry.deletes == 0


def test_repair_promotes_legacy_run_then_removes_it(monkeypatch, tmp_path) -> None:
    executable = (tmp_path / "Trace.exe").resolve()
    registry = FakeRegistry(f'"{executable}" --background')
    scheduler = FakeScheduler()
    registration = _registration(
        monkeypatch,
        tmp_path,
        registry=registry,
        scheduler=scheduler,
    )

    assert registration.repair_if_needed() == "repaired"
    assert len(scheduler.registered) == 1
    assert registry.value is None


def test_repair_failure_preserves_legacy_run_fallback(monkeypatch, tmp_path) -> None:
    legacy = r'"C:\legacy\WorkTrace.exe" --background'
    registry = FakeRegistry(legacy)
    scheduler = FakeScheduler()
    scheduler.fail_register = True
    registration = _registration(
        monkeypatch,
        tmp_path,
        registry=registry,
        scheduler=scheduler,
    )

    with pytest.raises(OSError, match="scheduler denied"):
        registration.repair_if_needed()

    assert registry.value == legacy
    assert registry.deletes == 0


def test_repair_cleans_legacy_fallback_when_task_is_already_canonical(
    monkeypatch, tmp_path
) -> None:
    registry = FakeRegistry("legacy")
    scheduler = FakeScheduler(exists=True, configured=True)
    registration = _registration(
        monkeypatch,
        tmp_path,
        registry=registry,
        scheduler=scheduler,
    )

    assert registration.repair_if_needed() == "repaired"
    assert scheduler.registered == []
    assert registry.value is None


class FakeTaskCollection:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.items: list[SimpleNamespace] = []

    @property
    def Count(self) -> int:
        return len(self.items)

    def Create(self, item_type: int) -> SimpleNamespace:
        if self.kind == "trigger":
            item = SimpleNamespace(
                Type=item_type,
                Id="",
                UserId="",
                Delay="",
                Enabled=False,
            )
        else:
            item = SimpleNamespace(
                Type=item_type,
                Path="",
                Arguments="",
                WorkingDirectory="",
            )
        self.items.append(item)
        return item

    def Item(self, index: int) -> SimpleNamespace:
        return self.items[index - 1]


class FakeTaskDefinition:
    def __init__(self) -> None:
        self.RegistrationInfo = SimpleNamespace(Description="")
        self.Principal = SimpleNamespace(UserId="", LogonType=0, RunLevel=0)
        self.Triggers = FakeTaskCollection("trigger")
        self.Actions = FakeTaskCollection("action")
        self.Settings = SimpleNamespace(
            Enabled=False,
            StartWhenAvailable=False,
            DisallowStartIfOnBatteries=True,
            StopIfGoingOnBatteries=True,
            ExecutionTimeLimit="",
            MultipleInstances=0,
            Priority=7,
        )


class FakeTaskRoot:
    def __init__(self) -> None:
        self.task: SimpleNamespace | None = None
        self.registration_args: tuple[object, ...] | None = None

    def RegisterTaskDefinition(
        self,
        name,
        definition,
        flags,
        user_id,
        password,
        logon_type,
    ) -> None:
        assert name == TASK_NAME
        self.registration_args = (flags, user_id, password, logon_type)
        self.task = SimpleNamespace(Enabled=True, Definition=definition)

    def GetTask(self, name: str) -> SimpleNamespace:
        assert name == TASK_NAME
        assert self.task is not None
        return self.task


class FakeTaskService:
    def __init__(self, definition: FakeTaskDefinition) -> None:
        self.definition = definition

    def NewTask(self, flags: int) -> FakeTaskDefinition:
        assert flags == 0
        return self.definition


class FakeComError(Exception):
    def __init__(self, inner_hresult: int) -> None:
        self.hresult = -2147352567
        super().__init__(
            self.hresult,
            "Exception occurred.",
            (0, None, None, None, 0, inner_hresult),
            None,
        )


class FakeMissingTaskRoot:
    def GetTask(self, name: str) -> None:
        assert name == TASK_NAME
        raise FakeComError(-2147024894)

    def DeleteTask(self, name: str, flags: int) -> None:
        assert name == TASK_NAME
        assert flags == 0
        raise FakeComError(-2147024894)


def test_nested_task_not_found_hresult_is_treated_as_absent(monkeypatch) -> None:
    scheduler = WindowsTaskScheduler()
    root = FakeMissingTaskRoot()
    monkeypatch.setattr(scheduler, "_root_folder", lambda: (object(), root))

    assert scheduler.exists(TASK_NAME) is False
    scheduler.delete(TASK_NAME)


def test_canonical_task_requires_zero_delay_and_normal_priority(
    monkeypatch, tmp_path
) -> None:
    definition = FakeTaskDefinition()
    service = FakeTaskService(definition)
    root = FakeTaskRoot()
    scheduler = WindowsTaskScheduler()
    monkeypatch.setattr(scheduler, "_root_folder", lambda: (service, root))
    monkeypatch.setattr(windows_startup, "_current_user_sid", lambda: "S-1-5-21-test")
    spec = StartupTaskSpec(
        executable_path=tmp_path / "Trace.exe",
        arguments=BACKGROUND_ARGUMENT,
        working_directory=tmp_path,
    )

    scheduler.register(TASK_NAME, spec)

    trigger = definition.Triggers.Item(1)
    assert root.registration_args == (6, "S-1-5-21-test", None, 3)
    assert trigger.Delay == "PT0S"
    assert definition.Settings.Priority == 6
    assert scheduler.is_configured(TASK_NAME, spec) is True

    trigger.Delay = ""
    assert scheduler.is_configured(TASK_NAME, spec) is True

    definition.Settings.Priority = 7
    assert scheduler.is_configured(TASK_NAME, spec) is False

    definition.Settings.Priority = 6
    trigger.Delay = "PT5S"
    assert scheduler.is_configured(TASK_NAME, spec) is False


def test_frozen_entry_does_not_own_launch_at_login_repair_thread() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "pyinstaller_entry.py").read_text(
        encoding="utf-8"
    )

    assert "_start_launch_at_login_repair" not in source
    assert "repair_launch_at_login_for_current_user" not in source
    assert "worktrace-launch-at-login-repair" not in source


def test_installer_applies_selected_startup_intent_without_unconditional_migration() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "installer" / "WorkTrace.iss").read_text(encoding="utf-8")

    assert "StartupTaskName = 'WorkTrace Launch At Login'" in source
    assert "ScheduledStartupTaskExists" in source
    assert "{sys}\\schtasks.exe" in source
    assert (
        'Parameters: "--configure-launch-at-login enable"; '
        "Flags: runhidden waituntilterminated; Tasks: startup"
        in source
    )
    assert (
        'Parameters: "--configure-launch-at-login disable"; '
        "Flags: runhidden waituntilterminated; Tasks: not startup"
        in source
    )
    assert 'Parameters: "--configure-launch-at-login migrate"' not in source
