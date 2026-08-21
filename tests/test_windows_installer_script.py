"""Static per-user Inno Setup installer contracts."""
from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.desktop.update_shutdown import UPDATE_SHUTDOWN_EVENT_NAME

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.serial]

ROOT = Path(__file__).resolve().parents[1]
ISS_PATH = ROOT / "installer" / "WorkTrace.iss"
BUILD_PATH = ROOT / "scripts" / "build_windows_installer.ps1"
RELEASE_BUILD_PATH = ROOT / "scripts" / "build_windows_release.ps1"
ICON_VERIFY_PATH = ROOT / "scripts" / "verify_windows_exe_icon.py"
INSTALLED_LAUNCH_SMOKE_PATH = ROOT / "scripts" / "smoke_installed_launch.ps1"
PACKAGE_ACTION_PATH = (
    ROOT / ".github" / "actions" / "build-windows-package" / "action.yml"
)
INSTALLER_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "installer-validation.yml"
INSTALLER_RUNTIME_SMOKE_PATH = ROOT / "scripts" / "ci" / "installer_runtime_smoke.ps1"


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


def test_upgrade_signals_native_shutdown_event_with_force_only_as_fallback() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    shutdown = source[
        source.index("function RequestWorkTraceShutdown") :
        source.index("function IsUsableWebView2Version")
    ]

    assert "CloseApplications=force" in source
    assert "RestartApplications=no" in source
    assert f"MaintenanceShutdownEventName = '{UPDATE_SHUTDOWN_EVENT_NAME}'" in source
    assert "OpenEventW@kernel32.dll" in source
    assert "SetEvent@kernel32.dll" in source
    assert "MaintenanceShutdownEventExists" in shutdown
    assert "SignalMaintenanceShutdownEvent" in shutdown
    assert "RequestWorkTraceShutdown('upgrade')" in source
    assert "MaintenanceShutdownArgument" not in source
    assert "Exec(" not in shutdown
    assert "ewWaitUntilTerminated" not in shutdown
    assert "WizardForm.Repaint" in source
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


def test_installer_and_shortcuts_use_one_cache_busted_canonical_icon() -> None:
    source = ISS_PATH.read_text(encoding="utf-8")
    assert '#define MyInstalledIconName "Trace-Icon-" + MyAppVersion + ".ico"' in source
    assert "#ifndef MyBrandIcon" in source
    assert r'#define MyBrandIcon "..\build\brand\worktrace.ico"' in source
    assert "SetupIconFile={#MyBrandIcon}" in source
    assert r"UninstallDisplayIcon={app}\{#MyInstalledIconName}" in source
    assert (
        r'Source: "{#MyBrandIcon}"; DestDir: "{app}"; '
        r'DestName: "{#MyInstalledIconName}"; Flags: ignoreversion'
        in source
    )
    assert r'Type: files; Name: "{app}\Trace-Icon-*.ico"' in source
    assert (
        r'Name: "{group}\有迹"; Filename: "{app}\{#MyAppExeName}"; '
        r'WorkingDir: "{app}"; IconFilename: "{app}\{#MyInstalledIconName}"'
        in source
    )
    assert (
        r'Name: "{autodesktop}\有迹"; Filename: "{app}\{#MyAppExeName}"; '
        r'WorkingDir: "{app}"; IconFilename: "{app}\{#MyInstalledIconName}"; '
        r'Tasks: desktopicon'
        in source
    )


def test_build_script_keeps_versioned_trace_output_contract() -> None:
    source = BUILD_PATH.read_text(encoding="utf-8")
    installer = ISS_PATH.read_text(encoding="utf-8")
    assert "ISCC.exe" in source
    assert "ISCC_PATH" in source
    assert "installer\\WorkTrace.iss" in source
    assert "dist\\Trace.exe" in source
    assert "dist\\Trace-Setup-$version.exe" in source
    assert '$compatTarget' not in source
    assert "Copy-Item -Force -LiteralPath $target -Destination" not in source
    assert "#ifndef MyAppVersion" in installer
    assert '#define MyAppVersion "0.1"' in installer
    assert "/DMyAppExe=$exe" in source
    assert "/DMyAppVersion=$version" in source
    assert "/DMyBrandIcon=$brandIcon" in source
    assert "/O$distPath" in source
    assert "/F$name" in source
    assert "$installerSource" in source
    assert "$LASTEXITCODE" in source
    assert "verify_windows_exe_icon.py" in source
    assert "--exe $target" in source
    assert "--ico $brandIcon" in source
    assert "generate_brand_icon.py" not in source
    assert "[regex]::Replace" not in source
    assert "WorkTrace.generated." not in source
    assert "Set-Content -LiteralPath $generatedInstaller" not in source


def test_compiled_installer_icon_is_verified_from_pe_resources() -> None:
    source = ICON_VERIFY_PATH.read_text(encoding="utf-8")
    assert "RT_ICON = 3" in source
    assert "RT_GROUP_ICON = 14" in source
    assert "LoadLibraryExW" in source
    assert "EnumResourceNamesW" in source
    assert "canonical payload embedded" in source
    assert "shell icon cache" in source


def test_build_script_auto_discovers_local_inno_setup_installation() -> None:
    source = BUILD_PATH.read_text(encoding="utf-8")
    assert '${env:ProgramFiles(x86)}' in source
    assert '$env:ProgramFiles' in source
    assert r'"Inno Setup 6\ISCC.exe"' in source
    assert r"'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'" in source
    assert r"'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'" in source
    assert r"'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'" in source
    assert "Get-ItemProperty $key -ErrorAction SilentlyContinue" in source
    assert "InstallLocation" in source
    assert source.index("Get-Command ISCC.exe") < source.index("${env:ProgramFiles(x86)}")


def test_local_installer_accepts_inno_setup_6_3_and_newer() -> None:
    source = BUILD_PATH.read_text(encoding="utf-8")
    assert '$minimumInnoVersion = "6.3.0"' in source
    assert "$minimumPreprocVersion = 100859904" in source
    assert "$actualPreprocVersion -lt $minimumPreprocVersion" in source
    assert '$expectedInnoVersion = "6.7.3"' not in source
    assert "$expectedPreprocVersion = 101122816" not in source


def test_release_build_generates_only_current_trace_release_artifacts() -> None:
    source = RELEASE_BUILD_PATH.read_text(encoding="utf-8")
    assert 'Join-Path $distPath "Trace.exe"' not in source
    assert 'Join-Path $stagingDistPath "Trace.exe"' in source
    assert 'Join-Path $distPath "Trace-$version.exe"' in source
    assert 'Join-Path $distPath "Trace-Setup-$version.exe"' in source
    assert 'Join-Path $repoRoot "build\\brand\\worktrace.ico"' in source
    assert 'Join-Path $repoRoot "build\\release-staging"' in source
    assert "--distpath $stagingDistPath" in source
    assert "--workpath $stagingWorkPath" in source
    assert "Copy-Item -Force -LiteralPath $stagedExePath -Destination $portablePath" in source
    assert "ExePath = $stagedExePath" in source
    assert "$compatSetupPath" not in source
    assert "Remove-CanonicalReleaseArtifact" in source
    assert "ExecutablePath" in source
    assert "[System.StringComparison]::OrdinalIgnoreCase" in source
    assert "Stop-Process -Id $process.ProcessId -Force" in source
    assert "build_windows_installer.ps1" in source
    assert "verify_windows_exe_icon.py" in source
    assert "--exe $stagedExePath" in source
    assert "--ico $brandIconPath" in source
    assert "PyInstaller generated Trace.exe without the canonical 有迹 icon." in source
    assert "PyInstaller completed without generating the staged Trace.exe" in source
    assert "Canonical Windows release contains unexpected executable artifacts" in source
    assert "Installer build completed without generating dist\\Trace-Setup-$version.exe" in source
    assert "Installer build completed without generating dist\\Trace-Setup.exe" not in source


def test_installer_runtime_smoke_resolves_versioned_setup_by_default() -> None:
    source = INSTALLER_RUNTIME_SMOKE_PATH.read_text(encoding="utf-8")
    assert '[string]$SetupPath = ""' in source
    assert "from worktrace.version import __version__" in source
    assert '"dist\\Trace-Setup-$version.exe"' in source


def test_retired_copy_installer_is_removed() -> None:
    assert not (ROOT / "scripts" / "windows_installer.py").exists()


def test_ci_prepares_one_pinned_verified_inno_setup_version() -> None:
    action = PACKAGE_ACTION_PATH.read_text(encoding="utf-8")
    assert "innosetup-6.7.3.exe" in action
    assert "is-6_7_3" in action
    assert "9C73C3BAE7ED48D44112A0F48E66742C00090BDB5BEF71D9D3C056C66E97B732" in action
    assert "ISCC_PATH=" in action
    assert "Unexpected release executable artifacts" in action
    assert "Release staging residue remained after the canonical build" in action


def test_ci_exercises_running_app_upgrade_and_uninstall_paths() -> None:
    workflow = INSTALLER_WORKFLOW_PATH.read_text(encoding="utf-8")
    runtime = INSTALLER_RUNTIME_SMOKE_PATH.read_text(encoding="utf-8")

    assert "Exercise installer runtime lifecycle" in workflow
    assert r"scripts\ci\installer_runtime_smoke.ps1" in workflow
    assert "worktrace-installer-smoke" in runtime
    assert '"C:\\legacy\\WorkTrace.exe" --background' in runtime
    assert '"Upgrade install"' in runtime
    assert runtime.count('/TASKS=`"startup`"') >= 2
    assert "/NOFORCECLOSEAPPLICATIONS" in runtime
    assert runtime.count("-KeepRunning") >= 2
    assert "unins000.exe" in runtime
    assert "Get-ItemPropertyValue" in runtime
    assert "Get-ItemProperty" in runtime


def test_installed_launch_smoke_targets_trace_but_keeps_legacy_state_root() -> None:
    smoke = INSTALLED_LAUNCH_SMOKE_PATH.read_text(encoding="utf-8")
    assert 'Join-Path $InstallDir "Trace.exe"' in smoke
    assert 'Join-Path $smokeRoot "WorkTrace"' in smoke
    assert 'Join-Path $appStateRoot "logs\\worktrace.log"' in smoke
    assert "Start-Process -FilePath $exe -PassThru" in smoke
    assert 'SimpleMatch "desktop shell window loaded"' in smoke
    assert "Remove-Item -Force -LiteralPath $appLog" in smoke
    assert "Invoke-MaintenanceShutdownControl" in smoke
    assert "[switch]$KeepRunning" in smoke
    assert "[string]$PidFile" in smoke
