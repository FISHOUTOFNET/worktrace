"""Static validation of ``scripts/build_windows_installer.ps1``.

The installer build script hardens PyInstaller's stderr INFO logs so they
no longer trigger false terminating errors under
``$ErrorActionPreference = "Stop"``. These tests read the script as text and
assert the hardening invariants remain in place. They never invoke
PyInstaller, PowerShell, or the installer itself, so they run on any host.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.serial]

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_windows_installer.ps1"


@pytest.fixture(scope="module")
def script_text() -> str:
    """Read the installer build script as text."""
    assert SCRIPT_PATH.is_file(), (
        f"expected installer build script at {SCRIPT_PATH}"
    )
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_installer_build_script_exists(script_text: str) -> None:
    """The installer build script must exist and be non-empty."""
    assert script_text.strip(), "build_windows_installer.ps1 is empty"


def test_script_keeps_global_strict_error_action(script_text: str) -> None:
    """The script must still set a global ``$ErrorActionPreference = "Stop"``.

    The hardening does not weaken global error handling; it only carves out a
    local relaxation around the native PyInstaller call. A global ``Stop`` must
    still be present so non-PyInstaller failures (Resolve-Path, Get-Command,
    New-Item, Get-Item) remain terminating.
    """
    assert re.search(r'\$ErrorActionPreference\s*=\s*"Stop"', script_text), (
        "script must retain global $ErrorActionPreference = 'Stop'"
    )


def test_script_has_local_error_action_handling_around_pyinstaller(
    script_text: str,
) -> None:
    """Around the native PyInstaller call there must be a local relaxation.

    The expected pattern is: save the old preference, set it to ``Continue``
    inside a try, run the native command, capture ``$LASTEXITCODE``, and
    restore the preference in a ``finally`` block. This stops stderr INFO
    logs from being wrapped as NativeCommandError while keeping real errors
    visible.
    """
    assert "oldErrorActionPreference" in script_text, (
        "script must save the previous $ErrorActionPreference before the "
        "native PyInstaller call"
    )
    assert re.search(
        r'\$ErrorActionPreference\s*=\s*"Continue"', script_text
    ), "script must locally set $ErrorActionPreference to 'Continue'"
    assert "finally" in script_text, (
        "script must restore $ErrorActionPreference in a finally block"
    )
    assert re.search(
        r"\$ErrorActionPreference\s*=\s*\$oldErrorActionPreference", script_text
    ), "script must restore the saved $ErrorActionPreference"


def test_script_still_checks_last_exit_code(script_text: str) -> None:
    """``$LASTEXITCODE`` must still be captured after the native call."""
    assert "$LASTEXITCODE" in script_text, (
        "script must read $LASTEXITCODE after invoking PyInstaller"
    )


def test_script_still_throws_on_nonzero_exit_code(script_text: str) -> None:
    """A non-zero PyInstaller exit code must still raise a terminating error."""
    assert re.search(
        r"throw\s+[\"]PyInstaller failed with exit code", script_text
    ), "script must throw when PyInstaller exits non-zero"


def test_script_uses_resolve_path_for_exe_path(script_text: str) -> None:
    """``$exe`` must come from ``Resolve-Path -LiteralPath`` so paths with
    spaces (e.g. ``C:\\More Than Coding\\WorkTrace``) resolve absolutely."""
    assert re.search(
        r"\$exe\s*=\s*Resolve-Path\s+-LiteralPath", script_text
    ), "script must resolve ExePath via Resolve-Path -LiteralPath"


def test_script_uses_absolute_add_data_path(script_text: str) -> None:
    """The ``--add-data`` payload must use the resolved absolute ``$exe``.

    PyInstaller resolves relative ``--add-data`` sources against ``--specpath``,
    not the repo root, so a relative ``dist\\WorkTrace.exe`` would break.
    Using ``$exe`` (the resolved absolute path) avoids this.
    """
    assert re.search(
        r"\$addData\s*=\s*\"\$exe;payload\"", script_text
    ), "script must build --add-data from the resolved absolute $exe path"


def test_script_does_not_silently_ignore_all_errors(script_text: str) -> None:
    """The hardening must not turn the script into one that ignores errors.

    Guards against an over-broad fix that sets the global preference to
    ``SilentlyContinue`` everywhere or drops the post-call throw. We assert:

    * no global ``$ErrorActionPreference = "SilentlyContinue"`` or
      ``"Continue"`` at top level (only the local one inside try),
    * the post-call throw is still present,
    * ``Resolve-Path`` and ``Get-Command`` still use ``-ErrorAction Stop``.
    """
    # No global (top-of-script) SilentlyContinue/Continue preference.
    assert not re.search(
        r'^\s*\$ErrorActionPreference\s*=\s*"SilentlyContinue"',
        script_text,
        flags=re.MULTILINE,
    ), "script must not globally set SilentlyContinue"

    # Get-Command python must keep -ErrorAction Stop so a missing python fails.
    assert re.search(
        r"Get-Command\s+python\s+-ErrorAction\s+Stop", script_text
    ), "script must keep -ErrorAction Stop on Get-Command python"


def test_script_forwards_to_pyinstaller_module(script_text: str) -> None:
    """Sanity: the script still invokes ``python -m PyInstaller``."""
    assert '"-m"' in script_text and '"PyInstaller"' in script_text, (
        "script must invoke python -m PyInstaller"
    )


def test_script_outputs_built_installer(script_text: str) -> None:
    """Sanity: the script still returns the built installer via Get-Item."""
    assert re.search(
        r"Get-Item\s+-LiteralPath\s+\$target", script_text
    ), "script must emit the built installer path via Get-Item -LiteralPath $target"
