"""Installer bootstrap contracts for optional integrations and privacy."""
from __future__ import annotations

from pathlib import Path

from worktrace.constants import PRIVACY_NOTICE_VERSION
from worktrace.desktop.install_bootstrap import (
    ENABLE_FD_WORK_VALUE,
    INSTALL_BOOTSTRAP_KEY,
    PENDING_PRIVACY_NOTICE_VALUE,
    PRIVACY_NOTICE_VALUE,
    consume_fd_work_install_intent,
    consume_privacy_install_intent,
)

ROOT = Path(__file__).resolve().parents[1]


class _FakeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_QUERY_VALUE = 0x0001
    KEY_SET_VALUE = 0x0002

    def __init__(
        self,
        *,
        value=1,
        exists: bool = True,
        values: dict[str, object] | None = None,
    ) -> None:
        self.exists = exists
        if values is None:
            self.values = {ENABLE_FD_WORK_VALUE: value} if exists else {}
        else:
            self.values = dict(values)
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


def test_privacy_intent_persists_through_application_service_and_is_consumed() -> None:
    registry = _FakeRegistry(
        values={
            PRIVACY_NOTICE_VALUE: PRIVACY_NOTICE_VERSION,
            PENDING_PRIVACY_NOTICE_VALUE: PRIVACY_NOTICE_VERSION,
        }
    )
    accepted_versions: list[str] = []

    assert consume_privacy_install_intent(
        accept_notice=lambda version: accepted_versions.append(version) or True,
        registry=registry,
        platform="win32",
    ) is True
    assert accepted_versions == [PRIVACY_NOTICE_VERSION]
    assert registry.values == {PRIVACY_NOTICE_VALUE: PRIVACY_NOTICE_VERSION}
    assert registry.closed is True
    assert registry.key_deleted is False


def test_privacy_persistence_failure_keeps_intent_retryable() -> None:
    registry = _FakeRegistry(
        values={PENDING_PRIVACY_NOTICE_VALUE: PRIVACY_NOTICE_VERSION}
    )

    assert consume_privacy_install_intent(
        accept_notice=lambda _version: False,
        registry=registry,
        platform="win32",
    ) is False
    assert registry.values == {
        PENDING_PRIVACY_NOTICE_VALUE: PRIVACY_NOTICE_VERSION
    }
    assert registry.closed is True


def test_invalid_privacy_version_is_discarded_without_persisting() -> None:
    registry = _FakeRegistry(values={PENDING_PRIVACY_NOTICE_VALUE: "999"})
    accepted_versions: list[str] = []

    assert consume_privacy_install_intent(
        accept_notice=lambda version: accepted_versions.append(version) or True,
        registry=registry,
        platform="win32",
    ) is False
    assert accepted_versions == []
    assert registry.values == {}
    assert registry.key_deleted is True


def test_application_consumes_privacy_intent_only_for_normal_startup() -> None:
    source = (ROOT / "worktrace" / "main.py").read_text(encoding="utf-8")
    maintenance_index = source.index("if options.shutdown_for_maintenance:")
    maintenance_return_index = source.index(
        "return 0 if request_running_instance_shutdown(timeout_seconds=20.0) else 5"
    )
    privacy_index = source.index("consume_privacy_install_intent()")
    webview_index = source.index("from .webview_main import main as webview_main")

    assert maintenance_index < maintenance_return_index < privacy_index < webview_index


def test_composition_root_consumes_intent_before_authorized_startup() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    main_source = source[source.index("def main(*, background: bool = False)") :]
    build_index = main_source.index("services = build_application_services(")
    consume_index = main_source.index(
        "consume_fd_work_install_intent(services.fd_work)"
    )
    startup_index = main_source.index("_prepare_post_privacy_startup(")

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


def test_installer_privacy_bootstrap_does_not_cold_start_trace_after_progress() -> None:
    source = (ROOT / "installer" / "WorkTrace.iss").read_text(encoding="utf-8")

    assert f"PrivacyNoticeVersion = '{PRIVACY_NOTICE_VERSION}';" in source
    assert "PendingPrivacyNoticeValueName = 'PendingPrivacyNoticeVersion';" in source
    assert "StagePrivacyAcceptanceForApplication;" in source
    assert "--accept-privacy-notice" not in source
    assert "ewWaitUntilTerminated" in source  # maintenance shutdown remains synchronous
    assert "正在关闭正在运行的有迹并准备安装，请稍候..." in source
    assert "CompareText(Trim(ExistingValue), '2') = 0" in source
