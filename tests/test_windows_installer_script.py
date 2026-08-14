"""Static per-user Inno Setup installer contracts."""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.serial]

ROOT = Path(__file__).resolve().parents[1]
ISS_PATH = ROOT / "installer" / "WorkTrace.iss"
BUILD_PATH = ROOT / "scripts" / "build_windows_installer.ps1"
RELEASE_BUILD_PATH = ROOT / "scripts" / "build_windows_release.ps1"
INSTALLED_LAUNCH_SMOKE_PATH = ROOT / "scripts" / "smoke_installed_launch.ps1"


def test_inno_setup_is_per_user_and_uses_trace_install_identity() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in source
    assert r"DefaultDirName={localappdata}\Programs\Trace" in source
    assert "DefaultGroupName=有迹" in source
    assert "Program Files" not in source
    assert "Root: HKLM" not in source
    assert "[Service]" not in source


def test_legacy_app_id_is_retained_for_in_place_upgrade() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "AppId=WorkTrace" in source
    assert 'LegacyAppExeName "WorkTrace.exe"' in source
    assert r"Uninstall\WorkTrace_is1" in source
    assert "ExistingApplicationExePath" in source
    assert r"{app}\{#LegacyAppExeName}" in source
    assert "[InstallDelete]" in source
    assert r'{group}\WorkTrace.lnk' in source
    assert r'{autodesktop}\WorkTrace.lnk' in source


def test_webview2_prerequisite_is_detected_and_installed_per_user() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" in source
    assert "https://go.microsoft.com/fwlink/p/?LinkId=2124703" in source
    assert "IsWebView2RuntimeInstalled" in source
    assert "RegQueryStringValue(HKCU" in source
    assert "RegQueryStringValue(HKLM32" in source
    assert "RegQueryStringValue(HKLM64" in source
    assert "PrepareToInstall" in source
    assert "DownloadTemporaryFile" in source
    assert "MicrosoftEdgeWebview2Setup.exe" in source
    assert "'/silent /install'" in source
    assert "PrivilegesRequired=lowest" in source


def test_upgrade_delegates_shutdown_with_force_only_as_fallback() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "CloseApplications=force" in source
    assert "RestartApplications=no" in source
    assert "MaintenanceShutdownArgument = '--shutdown-for-maintenance'" in source
    assert "RequestWorkTraceShutdown('upgrade')" in source
    assert "ewWaitUntilTerminated" in source
    assert "Restart Manager can apply the configured fallback" in source


def test_uninstall_requires_running_app_to_exit_cooperatively() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "function InitializeUninstall: Boolean" in source
    assert "RequestWorkTraceShutdown('uninstall')" in source
    assert "有迹未能在卸载前正常退出" in source


def test_startup_task_preserves_legacy_value_name_but_targets_trace_exe() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "Name: startup" in source
    assert "登录 Windows 时自动启动有迹" in source
    assert "Root: HKCU" in source
    assert r"Software\Microsoft\Windows\CurrentVersion\Run" in source
    assert 'ValueName: "WorkTrace"' in source
    assert 'ValueData: """{app}\\Trace.exe"" --background"' in source
    assert "uninsdeletevalue" in source
    assert "CurUninstallStepChanged" in source
    assert "Tasks: not startup" in source
    assert "Flags: deletevalue" in source


def test_upgrade_task_selection_preserves_actual_registry_choice() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "IsUpgradeInstall" in source
    assert "ExistingStartupEnabled" in source
    assert "WizardSelectTasks('startup')" in source
    assert "WizardSelectTasks('!startup')" in source
    assert "UsePreviousTasks=no" in source


def test_first_postinstall_launch_is_visible_normal_mode() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    run_section = source[source.index("[Run]") : source.index("[Code]")]
    assert r'Filename: "{app}\{#MyAppExeName}"' in run_section
    assert "--background" not in run_section
    assert "启动有迹" in run_section


def test_installer_and_shortcut_use_canonical_icon() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert r"SetupIconFile=..\worktrace\assets\worktrace.ico" in source
    assert "UninstallDisplayIcon={app}\\{#MyAppExeName}" in source
    assert r'Name: "{group}\有迹"' in source
    assert r'Name: "{autodesktop}\有迹"' in source


def test_build_script_keeps_trace_output_contract() -> None:
    source = BUILD_PATH.read_text(encoding="utf-8")
    assert "ISCC.exe" in source
    assert "ISCC_PATH" in source
    assert "installer\\WorkTrace.iss" in source
    assert "dist\\Trace.exe" in source
    assert "dist\\Trace-Setup.exe" in source
    assert "/DMyAppExe=" in source
    assert "/O$distPath" in source
    assert "/F$name" in source
    assert "$LASTEXITCODE" in source


def test_release_build_generates_trace_artifacts() -> None:
    source = RELEASE_BUILD_PATH.read_text(encoding="utf-8")
    assert 'Join-Path $repoRoot "dist\\Trace.exe"' in source
    assert 'Join-Path $repoRoot "dist\\Trace-Setup.exe"' in source
    pyinstaller_call = "& python -m PyInstaller --noconfirm --clean WorkTrace.spec"
    assert pyinstaller_call in source
    assert "build_windows_installer.ps1" in source
    assert "PyInstaller completed without generating dist\\Trace.exe" in source
    assert "Installer build completed without generating dist\\Trace-Setup.exe" in source


def test_retired_copy_installer_is_removed() -> None:
    assert not (ROOT / "scripts" / "windows_installer.py").exists()


def test_ci_prepares_one_pinned_verified_inno_setup_version() -> None:
    workflow = (ROOT / ".github" / "workflows" / "_validation.yml").read_text(encoding="utf-8")
    assert "innosetup-6.7.3.exe" in workflow
    assert "is-6_7_3" in workflow
    assert "9C73C3BAE7ED48D44112A0F48E66742C00090BDB5BEF71D9D3C056C66E97B732" in workflow
    assert "ISCC_PATH=" in workflow


def test_ci_exercises_running_app_upgrade_and_uninstall_paths() -> None:
    workflow = (ROOT / ".github" / "workflows" / "_validation.yml").read_text(encoding="utf-8")
    assert "Exercise installer upgrade runtime path" in workflow
    assert "worktrace-installer-smoke" in workflow
    assert '"C:\\legacy\\WorkTrace.exe" --background' in workflow
    assert '"Upgrade install"' in workflow
    assert workflow.count('/TASKS=`"startup`"') >= 2
    assert "/NOFORCECLOSEAPPLICATIONS" in workflow
    assert workflow.count("-KeepRunning") >= 2
    assert "unins000.exe" in workflow
    assert "Get-ItemPropertyValue" in workflow


def test_installed_launch_smoke_targets_trace_but_keeps_legacy_state_root() -> None:
    smoke = INSTALLED_LAUNCH_SMOKE_PATH.read_text(encoding="utf-8")
    assert 'Join-Path $InstallDir "Trace.exe"' in smoke
    assert '"WorkTrace\\logs\\worktrace.log"' in smoke
    assert "Start-Process -FilePath $exe -PassThru" in smoke
    assert 'SimpleMatch "desktop shell window loaded"' in smoke
    assert "[switch]$KeepRunning" in smoke
    assert "[string]$PidFile" in smoke
