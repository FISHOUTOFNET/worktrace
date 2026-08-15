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
    installer = BUILD_INSTALLER.read_text(encoding="utf-8")
    release = BUILD_RELEASE.read_text(encoding="utf-8")
    action = PACKAGE_ACTION.read_text(encoding="utf-8")

    version_import = "from worktrace.version import __version__; print(__version__)"
    assert version_import in installer
    assert version_import in release
    assert version_import in action
    assert 'dist\\Trace-Setup-$version.exe' in installer
    assert "MyAppVersion" in installer
    assert "[regex]::Replace" in installer
    assert 'dist\\Trace-$version.exe' in release
    assert 'dist\\Trace-Setup-$version.exe' in release
    assert 'Trace-$env:TRACE_VERSION.exe' in action
    assert 'Trace-Setup-$env:TRACE_VERSION.exe' in action


def test_unversioned_setup_name_is_compatibility_only() -> None:
    installer = BUILD_INSTALLER.read_text(encoding="utf-8")
    release = BUILD_RELEASE.read_text(encoding="utf-8")
    workflow = INSTALLER_WORKFLOW.read_text(encoding="utf-8")

    assert '$useDefaultOutput = -not $OutputPath' in installer
    assert 'Copy-Item -Force -LiteralPath $target -Destination $compatTarget' in installer
    assert '$compatSetupPath = Join-Path $repoRoot "dist\\Trace-Setup.exe"' in release
    assert "path: dist/Trace*.exe" in workflow
    assert '"worktrace/version.py"' in workflow
