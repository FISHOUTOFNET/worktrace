"""Release-version single-source contracts."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from worktrace import __version__ as package_version
from worktrace.constants import APP_VERSION
from worktrace.version import __version__ as canonical_version

pytestmark = [pytest.mark.packaging, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SOURCE = ROOT / "installer" / "WorkTrace.iss"
BUILD_INSTALLER = ROOT / "scripts" / "build_windows_installer.ps1"
BUILD_RELEASE = ROOT / "scripts" / "build_windows_release.ps1"
PACKAGE_ACTION = ROOT / ".github" / "actions" / "build-windows-package" / "action.yml"
INSTALLER_WORKFLOW = ROOT / ".github" / "workflows" / "installer-validation.yml"


def test_release_version_starts_at_0_0_1_and_has_one_runtime_source() -> None:
    assert canonical_version == "0.0.1"
    assert package_version == canonical_version
    assert APP_VERSION == canonical_version
    assert re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", canonical_version)


def test_windows_builds_stamp_and_name_artifacts_from_canonical_version() -> None:
    installer_source = INSTALLER_SOURCE.read_text(encoding="utf-8")
    installer = BUILD_INSTALLER.read_text(encoding="utf-8")
    release = BUILD_RELEASE.read_text(encoding="utf-8")
    action = PACKAGE_ACTION.read_text(encoding="utf-8")

    version_import = "from worktrace.version import __version__; print(__version__)"
    assert version_import in installer
    assert version_import in release
    assert version_import in action
    assert 'dist\\Trace-Setup-$version.exe' in installer
    assert "#ifndef MyAppVersion" in installer_source
    assert '#define MyAppVersion "0.1"' in installer_source
    assert '"/DMyAppVersion=$version"' in installer
    assert "[regex]::Replace" not in installer
    assert "WorkTrace.generated." not in installer
    assert 'Join-Path $distPath "Trace-$version.exe"' in release
    assert 'Join-Path $distPath "Trace-Setup-$version.exe"' in release
    assert 'Trace-$env:TRACE_VERSION.exe' in action
    assert 'Trace-Setup-$env:TRACE_VERSION.exe' in action


def test_unversioned_release_aliases_are_retired() -> None:
    installer = BUILD_INSTALLER.read_text(encoding="utf-8")
    release = BUILD_RELEASE.read_text(encoding="utf-8")
    action = PACKAGE_ACTION.read_text(encoding="utf-8")
    workflow = INSTALLER_WORKFLOW.read_text(encoding="utf-8")

    assert '$useDefaultOutput = -not $OutputPath' in installer
    assert '$compatTarget' not in installer
    assert 'Copy-Item -Force -LiteralPath $target -Destination' not in installer
    assert '$compatSetupPath' not in release
    assert 'Join-Path $distPath "Trace.exe"' not in release
    assert 'Join-Path $stagingDistPath "Trace.exe"' in release
    assert '"dist\\Trace-Setup.exe"' not in release
    assert "Unexpected release executable artifacts" in action
    assert r"dist\Trace.exe" not in action
    assert r"dist\Trace-Setup.exe" not in action
    assert "path: dist/Trace*.exe" in workflow
