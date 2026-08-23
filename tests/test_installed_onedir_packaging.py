from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.serial]

ROOT = Path(__file__).resolve().parents[1]


def test_spec_builds_portable_onefile_and_installed_onedir_from_one_analysis():
    source = (ROOT / "WorkTrace.spec").read_text(encoding="utf-8")

    assert "portable_exe = EXE(" in source
    assert "name='Trace-Portable'" in source
    assert "installed_exe = EXE(" in source
    assert "exclude_binaries=True" in source
    assert "installed_app = COLLECT(" in source
    assert "name='Trace'" in source


def test_release_build_uses_onedir_for_setup_and_onefile_for_portable_publication():
    source = (ROOT / "scripts" / "build_windows_release.ps1").read_text(
        encoding="utf-8"
    )

    assert 'Join-Path $stagingDistPath "Trace-Portable.exe"' in source
    assert 'Join-Path $stagingDistPath "Trace"' in source
    assert 'Join-Path $stagedInstalledDir "Trace.exe"' in source
    assert 'Join-Path $stagedInstalledDir "_internal"' in source
    assert "Copy-Item -Force -LiteralPath $stagedPortableExePath -Destination $portablePath" in source
    assert "$installerArgs = @{ ExePath = $stagedExePath; OutputPath = $setupPath }" in source


def test_installer_recursively_installs_onedir_runtime_and_cleans_old_internal_tree():
    installer = (ROOT / "installer" / "WorkTrace.iss").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_windows_installer.ps1").read_text(
        encoding="utf-8"
    )

    assert "#ifdef MyAppSourceDir" in installer
    assert 'Source: "{#MyAppSourceDir}\\*"' in installer
    assert "recursesubdirs createallsubdirs" in installer
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in installer
    assert '"/DMyAppSourceDir=$appSourceDir"' in builder
    assert '$isOneDirSource = Test-Path -LiteralPath (Join-Path $appSourceDir "_internal")' in builder
