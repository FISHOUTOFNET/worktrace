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


def test_inno_setup_is_per_user_and_never_requests_elevation() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in source
    assert r"DefaultDirName={localappdata}\Programs\WorkTrace" in source
    assert "DefaultGroupName=WorkTrace" in source
    assert "Program Files" not in source
    assert "Root: HKLM" not in source
    assert "[Service]" not in source


def test_webview2_prerequisite_is_detected_and_installed_per_user() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" in source
    assert "https://go.microsoft.com/fwlink/p/?LinkId=2124703" in source
    assert "IsWebView2RuntimeInstalled" in source
    assert "WebView2VersionIsPresent(HKCU" in source
    assert "WebView2VersionIsPresent(HKLM32" in source
    assert "PrepareToInstall" in source
    assert "DownloadTemporaryFile" in source
    assert "MicrosoftEdgeWebview2Setup.exe" in source
    assert "'/silent /install'" in source
    assert "PrivilegesRequired=lowest" in source


def test_upgrade_closes_running_app_without_restart_manager_relaunch() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "CloseApplications=yes" in source
    assert "RestartApplications=no" in source


def test_startup_task_writes_only_hkcu_and_is_uninstall_cleaned() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "Name: startup" in source
    assert "登录 Windows 时自动启动 WorkTrace" in source
    assert "Root: HKCU" in source
    assert r"Software\Microsoft\Windows\CurrentVersion\Run" in source
    assert 'ValueName: "WorkTrace"' in source
    assert 'ValueData: """{app}\\WorkTrace.exe"" --background"' in source
    assert "uninsdeletevalue" in source
    assert "CurUninstallStepChanged" in source
    assert "RegDeleteValue" in source
    assert "Tasks: not startup" in source
    assert "Flags: deletevalue" in source


def test_upgrade_task_selection_preserves_actual_registry_choice() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert "IsUpgradeInstall" in source
    assert "ExistingStartupEnabled" in source
    assert "RegQueryStringValue" in source
    assert "WizardSelectTasks('startup')" in source
    assert "WizardSelectTasks('!startup')" in source
    assert "UsePreviousTasks=no" in source


def test_startup_state_detection_does_not_depend_on_app_constant() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    helper_start = source.index("function ExistingStartupEnabled")
    helper_end = source.index("function WebView2VersionIsPresent", helper_start)
    helper = source[helper_start:helper_end]

    assert "RegQueryStringValue" in helper
    assert "Trim(ExistingValue) <> ''" in helper
    assert "{app}" not in helper
    assert "ExpandConstant" not in helper
    assert "ExpectedValue" not in helper
    assert "CompareText" not in helper


def test_first_postinstall_launch_is_visible_normal_mode() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    run_section = source[source.index("[Run]") : source.index("[Code]")]
    assert r'Filename: "{app}\{#MyAppExeName}"' in run_section
    assert "--background" not in run_section


def test_installer_and_shortcut_use_canonical_icon() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert r"SetupIconFile=..\worktrace\assets\worktrace.ico" in source
    assert "UninstallDisplayIcon={app}\\{#MyAppExeName}" in source
    assert "IconFilename: \"{app}\\{#MyAppExeName}\"" in source


def test_build_script_locates_iscc_and_keeps_output_contract() -> None:
    source = BUILD_PATH.read_text(encoding="utf-8")
    assert "ISCC.exe" in source
    assert "Inno Setup 6" in source
    assert "Inno Setup compiler ISCC.exe was not found" in source
    assert "installer\\WorkTrace.iss" in source
    assert "dist\\WorkTrace-Setup.exe" in source
    assert "/DMyAppExe=" in source
    assert "/O$distPath" in source
    assert "/F$name" in source
    assert "$LASTEXITCODE" in source
    assert "windows_installer.py" not in source
    assert "PyInstaller" not in source


def test_release_build_never_reuses_old_release_artifacts() -> None:
    source = RELEASE_BUILD_PATH.read_text(encoding="utf-8")
    assert 'Join-Path $repoRoot "build"' in source
    assert 'Join-Path $distPath "WorkTrace.exe"' in source
    assert 'Join-Path $distPath "WorkTrace-Setup.exe"' in source
    assert "Remove-Item -Recurse -Force -LiteralPath $buildPath" in source
    assert "foreach ($artifact in @($exePath, $setupPath))" in source
    assert "Remove-Item -Force -LiteralPath $artifact" in source
    pyinstaller_call = "& python -m PyInstaller --noconfirm --clean WorkTrace.spec"
    installer_call = "& $installerBuilder @installerArgs"
    assert pyinstaller_call in source
    assert "build_windows_installer.ps1" in source
    assert installer_call in source
    assert source.index(pyinstaller_call) < source.index(installer_call)
    assert "PyInstaller completed without generating dist\\WorkTrace.exe" in source
    assert (
        "Installer build completed without generating dist\\WorkTrace-Setup.exe"
        in source
    )


def test_retired_copy_installer_is_removed() -> None:
    assert not (ROOT / "scripts" / "windows_installer.py").exists()


def test_ci_prepares_one_pinned_verified_inno_setup_version() -> None:
    workflow = (ROOT / ".github" / "workflows" / "_validation.yml").read_text(
        encoding="utf-8"
    )
    assert "innosetup-6.7.3.exe" in workflow
    assert "is-6_7_3" in workflow
    assert (
        "9C73C3BAE7ED48D44112A0F48E66742C00090BDB5BEF71D9D3C056C66E97B732"
        in workflow
    )
    assert "ISCC_PATH=" in workflow


def test_ci_waits_for_inno_setup_bootstrap_before_using_iscc() -> None:
    workflow = (ROOT / ".github" / "workflows" / "_validation.yml").read_text(
        encoding="utf-8"
    )
    assert "Start-Process" in workflow
    assert "-Wait" in workflow
    assert "ExitCode" in workflow


def test_ci_exercises_installer_upgrade_runtime_path() -> None:
    workflow = (ROOT / ".github" / "workflows" / "_validation.yml").read_text(
        encoding="utf-8"
    )
    assert "Exercise installer upgrade runtime path" in workflow
    assert "worktrace-installer-smoke" in workflow
    assert '"C:\legacy\WorkTrace.exe" --background' in workflow
    assert '"Upgrade install"' in workflow
    assert workflow.count('/TASKS=`"startup`"') >= 2
    assert "unins000.exe" in workflow
    assert "Get-ItemPropertyValue" in workflow


def test_ci_launches_the_freshly_installed_application() -> None:
    workflow = (ROOT / ".github" / "workflows" / "_validation.yml").read_text(
        encoding="utf-8"
    )
    smoke = INSTALLED_LAUNCH_SMOKE_PATH.read_text(encoding="utf-8")

    assert 'smoke_installed_launch.ps1" -InstallDir $installDir' in workflow
    assert 'Join-Path $InstallDir "WorkTrace.exe"' in smoke
    assert "Start-Process -FilePath $exe -PassThru" in smoke
    assert 'SimpleMatch "desktop shell window loaded"' in smoke
    assert "$env:LOCALAPPDATA = $smokeRoot" in smoke
    assert "taskkill.exe /PID $process.Id /T /F" in smoke
