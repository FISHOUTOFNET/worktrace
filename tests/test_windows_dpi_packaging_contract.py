from __future__ import annotations

import runpy
from pathlib import Path

import pytest


pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.serial]

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "packaging" / "windows" / "trace.manifest.xml"
SPEC_PATH = ROOT / "WorkTrace.spec"
MAIN_PATH = ROOT / "worktrace" / "main.py"
RELEASE_SCRIPT_PATH = ROOT / "scripts" / "build_windows_release.ps1"
VERIFIER_PATH = ROOT / "scripts" / "verify_windows_exe_manifest.py"


def test_manifest_declares_per_monitor_v2_with_legacy_fallback_and_as_invoker():
    namespace = runpy.run_path(str(VERIFIER_PATH))
    source = MANIFEST_PATH.read_text(encoding="utf-8")
    assert namespace["_has_required_dpi_contract"](source) is True
    assert namespace["_has_required_dpi_contract"](
        source.replace("PerMonitorV2", "PerMonitor")
    ) is False


def test_both_windows_executables_embed_the_same_canonical_manifest():
    source = SPEC_PATH.read_text(encoding="utf-8")
    assert "app_manifest = root / 'packaging' / 'windows' / 'trace.manifest.xml'" in source
    assert source.count("manifest=str(app_manifest)") == 2


def test_dpi_guard_runs_before_webview_import():
    source = MAIN_PATH.read_text(encoding="utf-8")
    guard = source.index("configure_process_dpi_awareness()")
    webview_import = source.index("from .webview_main import main as webview_main")
    assert guard < webview_import


def test_release_build_verifies_manifest_on_installed_and_portable_executables():
    source = RELEASE_SCRIPT_PATH.read_text(encoding="utf-8")
    assert source.count("verify_windows_exe_manifest.py") == 2
    assert "--exe $stagedExePath" in source
    assert "--exe $stagedPortableExePath" in source
