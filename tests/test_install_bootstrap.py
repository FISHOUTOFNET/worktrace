"""Installer bootstrap contracts for optional integrations."""
from __future__ import annotations

from pathlib import Path

from worktrace.desktop.install_bootstrap import (
    ENABLE_FD_WORK_VALUE,
    INSTALL_BOOTSTRAP_KEY,
    consume_fd_work_install_intent,
)

ROOT = Path(__file__).resolve().parents[1]


class _FakeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_QUERY_VALUE = 0x0001
    KEY_SET_VALUE = 0x0002

    def __init__(self, *, value=1, exists: bool = True) -> None:
        self.exists = exists
        self.values = {ENABLE_FD_WORK_VALUE: value} if exists else {}
        self.open_calls = 0
        self.closed = False
        self.key_deleted = False

    def OpenKey(self, root, path, reserved, access):
        assert root is self.HKEY_CURRENT_USER
        assert path == INSTALL_BOOTSTRAP_KEY
        assert reserved == 0
        assert access == self.KEY_QUERY_VALUE | self.KEY_SET_VALUE
        self.open_calls += 1
        if not self.exists:
            raise FileNotFoundError(path)
        return self

    def QueryValueEx(self, key, name):
        assert key is self
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 4

    def DeleteValue(self, key, name):
        assert key is self
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]

    def CloseKey(self, key):
        assert key is self
        self.closed = True

    def DeleteKey(self, root, path):
        assert root is self.HKEY_CURRENT_USER
        assert path == INSTALL_BOOTSTRAP_KEY
        if self.values:
            raise OSError("key not empty")
        self.key_deleted = True


class _FakeFDWork:
    def __init__(self, *, status=None, error: Exception | None = None) -> None:
        self.status = {"enabled": True} if status is None else status
        self.error = error
        self.calls = []

    def set_enabled(self, enabled: bool):
        self.calls.append(enabled)
        if self.error is not None:
            raise self.error
        return self.status


def test_non_windows_never_reads_installer_registry() -> None:
    registry = _FakeRegistry()
    fd_work = _FakeFDWork()

    assert consume_fd_work_install_intent(
        fd_work,
        registry=registry,
        platform="linux",
    ) is False
    assert registry.open_calls == 0
    assert fd_work.calls == []


def test_selected_installer_intent_enables_plugin_and_is_consumed() -> None:
    registry = _FakeRegistry(value=1)
    fd_work = _FakeFDWork()

    assert consume_fd_work_install_intent(
        fd_work,
        registry=registry,
        platform="win32",
    ) is True
    assert fd_work.calls == [True]
    assert registry.values == {}
    assert registry.closed is True
    assert registry.key_deleted is True


def test_missing_installer_intent_keeps_plugin_default_unchanged() -> None:
    registry = _FakeRegistry(exists=False)
    fd_work = _FakeFDWork()

    assert consume_fd_work_install_intent(
        fd_work,
        registry=registry,
        platform="win32",
    ) is False
    assert fd_work.calls == []


def test_unconfirmed_plugin_enable_keeps_intent_retryable() -> None:
    registry = _FakeRegistry(value=1)
    fd_work = _FakeFDWork(status={"enabled": False})

    assert consume_fd_work_install_intent(
        fd_work,
        registry=registry,
        platform="win32",
    ) is False
    assert fd_work.calls == [True]
    assert registry.values == {ENABLE_FD_WORK_VALUE: 1}
    assert registry.closed is True
    assert registry.key_deleted is False


def test_plugin_enable_exception_keeps_intent_retryable() -> None:
    registry = _FakeRegistry(value=1)
    fd_work = _FakeFDWork(error=RuntimeError("settings unavailable"))

    assert consume_fd_work_install_intent(
        fd_work,
        registry=registry,
        platform="win32",
    ) is False
    assert fd_work.calls == [True]
    assert registry.values == {ENABLE_FD_WORK_VALUE: 1}


def test_invalid_bootstrap_value_is_removed_without_enabling_plugin() -> None:
    registry = _FakeRegistry(value=0)
    fd_work = _FakeFDWork()

    assert consume_fd_work_install_intent(
        fd_work,
        registry=registry,
        platform="win32",
    ) is False
    assert fd_work.calls == []
    assert registry.values == {}
    assert registry.key_deleted is True


def test_composition_root_consumes_intent_before_authorized_startup() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    build_index = source.index("services = build_application_services(")
    consume_index = source.index("consume_fd_work_install_intent(services.fd_work)")
    startup_index = source.index("app_control.start_if_authorized(pre_start=True)")

    assert build_index < consume_index < startup_index


def test_installer_exposes_default_tasks_and_red_fd_work_notice() -> None:
    source = (ROOT / "installer" / "WorkTrace.iss").read_text(encoding="utf-8")
    task_lines = [
        line for line in source.splitlines() if line.startswith("Name: ")
    ]

    assert 'GroupDescription: "附加任务："' in source
    assert 'Name: startup; Description: "登录 Windows 时自动启动有迹"' in source
    assert 'Name: desktopicon; Description: "创建桌面快捷方式"' in source
    assert 'Name: fdwork; Description: "启用 FD Work 插件"' in source

    for task_name in ("startup", "desktopicon", "fdwork"):
        task_line = next(
            line for line in task_lines if line.startswith(f"Name: {task_name};")
        )
        assert "Flags: unchecked" not in task_line

    assert (
        'Name: "{autodesktop}\\有迹"; Filename: "{app}\\{#MyAppExeName}"; '
        'WorkingDir: "{app}"; IconFilename: "{app}\\{#MyInstalledIconName}"; '
        'Tasks: desktopicon'
        in source
    )
    assert 'Subkey: "Software\\WorkTrace\\InstallBootstrap"' in source
    assert 'ValueName: "EnableFDWork"' in source
    assert "Tasks: fdwork" in source
    assert "Tasks: not fdwork" in source

    assert "FDWorkTaskNotice: TNewStaticText;" in source
    assert "FDWorkTaskNotice.Parent := WizardForm.SelectTasksPage;" in source
    assert "FDWorkTaskNotice.Font.Color := clRed;" in source
    assert (
        "'FD Work 仅方达律师事务所用户可用；非方达用户请取消勾选。';"
        in source
    )
    assert "ConfigureFDWorkTaskNotice;" in source
