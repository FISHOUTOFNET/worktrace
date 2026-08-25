from __future__ import annotations

import sys
from pathlib import Path

import pytest

from worktrace.platforms.windows_startup import (
    BACKGROUND_ARGUMENT,
    TASK_NAME,
    StartupTaskSpec,
    WindowsStartupRegistration,
)


class FakeRegistry:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.deletes = 0
        self.fail_delete = False

    def read_run_value(self, name: str) -> str | None:
        assert name == "WorkTrace"
        return self.value

    def delete_run_value(self, name: str) -> None:
        assert name == "WorkTrace"
        self.deletes += 1
        if self.fail_delete:
            raise OSError("registry denied")
        self.value = None


class FakeScheduler:
    def __init__(self, *, exists: bool = False, configured: bool = False) -> None:
        self.task_exists = exists
        self.configured = configured
        self.registered: list[tuple[str, StartupTaskSpec]] = []
        self.deleted: list[str] = []
        self.fail_register = False
        self.fail_delete = False

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
        self.deleted.append(name)
        if self.fail_delete:
            raise OSError("scheduler denied")
        self.task_exists = False
        self.configured = False


def _service(
    monkeypatch,
    executable: Path,
    *,
    registry: FakeRegistry | None = None,
    scheduler: FakeScheduler | None = None,
) -> WindowsStartupRegistration:
    monkeypatch.setattr(sys, "platform", "win32")
    return WindowsStartupRegistration(
        executable_path=executable,
        registry=registry or FakeRegistry(),
        scheduler=scheduler or FakeScheduler(),
    )


def test_startup_command_quotes_executable_path_with_spaces(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "More Than Coding" / "Trace.exe"
    service = _service(monkeypatch, executable)

    assert service.expected_command() == f'"{executable.resolve()}" --background'


def test_enable_registers_canonical_logon_task_and_removes_legacy_run(
    monkeypatch, tmp_path
) -> None:
    executable = tmp_path / "Trace.exe"
    registry = FakeRegistry(f'"{executable.resolve()}" --background')
    scheduler = FakeScheduler()
    service = _service(
        monkeypatch, executable, registry=registry, scheduler=scheduler
    )

    service.enable()

    assert scheduler.registered == [
        (
            TASK_NAME,
            StartupTaskSpec(
                executable_path=executable.resolve(),
                arguments=BACKGROUND_ARGUMENT,
                working_directory=executable.resolve().parent,
            ),
        )
    ]
    assert registry.value is None
    assert service.is_configured() is True


def test_enable_is_idempotent_but_still_cleans_legacy_run(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "Trace.exe"
    registry = FakeRegistry("legacy")
    scheduler = FakeScheduler(exists=True, configured=True)
    service = _service(
        monkeypatch, executable, registry=registry, scheduler=scheduler
    )

    service.enable()
    service.enable()

    assert scheduler.registered == []
    assert registry.value is None
    assert registry.deletes == 2


def test_registration_failure_keeps_legacy_run_as_fallback(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "Trace.exe"
    legacy = f'"{executable.resolve()}" --background'
    registry = FakeRegistry(legacy)
    scheduler = FakeScheduler()
    scheduler.fail_register = True
    service = _service(
        monkeypatch, executable, registry=registry, scheduler=scheduler
    )

    with pytest.raises(OSError, match="scheduler denied"):
        service.enable()

    assert registry.value == legacy
    assert registry.deletes == 0
    assert service.is_configured() is True


def test_migration_repairs_any_owned_legacy_run_and_deletes_it_after_verification(
    monkeypatch, tmp_path
) -> None:
    executable = tmp_path / "Trace.exe"
    registry = FakeRegistry(r'"C:\legacy\WorkTrace.exe" --background')
    scheduler = FakeScheduler()
    service = _service(
        monkeypatch, executable, registry=registry, scheduler=scheduler
    )

    service.migrate_legacy_registration()

    assert scheduler.configured is True
    assert registry.value is None


def test_migration_repairs_existing_task_without_enabling_disabled_user(
    monkeypatch, tmp_path
) -> None:
    executable = tmp_path / "Trace.exe"

    disabled_scheduler = FakeScheduler()
    disabled = _service(
        monkeypatch,
        executable,
        registry=FakeRegistry(),
        scheduler=disabled_scheduler,
    )
    disabled.migrate_legacy_registration()
    assert disabled_scheduler.registered == []

    stale_scheduler = FakeScheduler(exists=True, configured=False)
    stale = _service(
        monkeypatch,
        executable,
        registry=FakeRegistry(),
        scheduler=stale_scheduler,
    )
    stale.migrate_legacy_registration()
    assert len(stale_scheduler.registered) == 1
    assert stale.is_configured() is True


def test_disable_attempts_task_and_legacy_cleanup_even_if_one_fails(
    monkeypatch, tmp_path
) -> None:
    executable = tmp_path / "Trace.exe"
    registry = FakeRegistry("legacy")
    scheduler = FakeScheduler(exists=True, configured=True)
    scheduler.fail_delete = True
    service = _service(
        monkeypatch, executable, registry=registry, scheduler=scheduler
    )

    with pytest.raises(OSError, match="scheduler denied"):
        service.disable()

    assert scheduler.deleted == [TASK_NAME]
    assert registry.value is None


def test_legacy_run_counts_only_when_it_matches_current_command(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "Trace.exe"
    scheduler = FakeScheduler()

    current = _service(
        monkeypatch,
        executable,
        registry=FakeRegistry(f'"{executable.resolve()}" --background'),
        scheduler=scheduler,
    )
    assert current.is_configured() is True

    stale = _service(
        monkeypatch,
        executable,
        registry=FakeRegistry(r'"C:\Old\WorkTrace.exe" --background'),
        scheduler=scheduler,
    )
    assert stale.is_configured() is False


def test_source_run_never_registers_python_interpreter(monkeypatch) -> None:
    registry = FakeRegistry()
    scheduler = FakeScheduler()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Python311\python.exe")

    service = WindowsStartupRegistration(registry=registry, scheduler=scheduler)

    assert service.supported is False
    with pytest.raises(RuntimeError, match="launch_at_login_unsupported"):
        service.enable()
    assert scheduler.registered == []


def test_frozen_entry_exposes_only_narrow_startup_control_operations() -> None:
    entry = Path(__file__).resolve().parents[1] / "scripts" / "pyinstaller_entry.py"
    source = entry.read_text(encoding="utf-8")

    assert '_STARTUP_CONTROL_ARGUMENT = "--configure-launch-at-login"' in source
    assert 'operation not in {"enable", "disable", "migrate"}' in source
    assert "registration.migrate_legacy_registration()" in source
    assert source.index("_run_launch_at_login_control") < source.index("_run_application")
