from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.platforms.windows_startup import WindowsStartupRegistration


class FakeRegistry:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.writes: list[str] = []
        self.deletes = 0
        self.fail_write = False

    def read_run_value(self, name: str) -> str | None:
        assert name == "WorkTrace"
        return self.value

    def write_run_value(self, name: str, value: str) -> None:
        assert name == "WorkTrace"
        self.writes.append(value)
        if self.fail_write:
            raise OSError("registry denied")
        self.value = value

    def delete_run_value(self, name: str) -> None:
        assert name == "WorkTrace"
        self.deletes += 1
        self.value = None


def test_startup_command_quotes_executable_path_with_spaces() -> None:
    registry = FakeRegistry()
    service = WindowsStartupRegistration(
        executable_path=Path(r"C:\More Than Coding\WorkTrace\WorkTrace.exe"),
        registry=registry,
    )

    service.enable()

    assert registry.value == (
        r'"C:\More Than Coding\WorkTrace\WorkTrace.exe" --background'
    )
    assert service.is_configured() is True


def test_enable_and_disable_are_idempotent() -> None:
    expected = r'"C:\Apps\WorkTrace.exe" --background'
    registry = FakeRegistry(expected)
    service = WindowsStartupRegistration(
        executable_path=Path(r"C:\Apps\WorkTrace.exe"),
        registry=registry,
    )

    service.enable()
    service.enable()
    assert registry.writes == []

    service.disable()
    service.disable()
    assert registry.deletes == 1


@pytest.mark.parametrize(
    "value",
    [
        r'"C:\Old\WorkTrace.exe" --background',
        r'"C:\Apps\WorkTrace.exe"',
        r"C:\Apps\WorkTrace.exe --background",
    ],
)
def test_old_or_malformed_startup_value_is_not_configured(value: str) -> None:
    service = WindowsStartupRegistration(
        executable_path=Path(r"C:\Apps\WorkTrace.exe"),
        registry=FakeRegistry(value),
    )
    assert service.is_configured() is False


def test_write_failure_can_be_followed_by_authoritative_state_read() -> None:
    registry = FakeRegistry()
    registry.fail_write = True
    service = WindowsStartupRegistration(
        executable_path=Path(r"C:\Apps\WorkTrace.exe"),
        registry=registry,
    )

    with pytest.raises(OSError, match="registry denied"):
        service.enable()

    assert service.is_configured() is False
