from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest


pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.serial]

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "packaging" / "windows" / "trace.manifest.xml"
SPEC_PATH = ROOT / "WorkTrace.spec"
MAIN_PATH = ROOT / "worktrace" / "main.py"
RELEASE_SCRIPT_PATH = ROOT / "scripts" / "build_windows_release.ps1"
VERIFIER_PATH = ROOT / "scripts" / "verify_windows_exe_manifest.py"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def test_manifest_declares_per_monitor_v2_with_legacy_fallback_and_as_invoker():
    root = ElementTree.parse(MANIFEST_PATH).getroot()
    values: dict[str, list[str]] = {}
    execution_levels: list[str] = []
    for element in root.iter():
        name = _local_name(element.tag)
        values.setdefault(name, []).append((element.text or "").strip())
        if name == "requestedExecutionLevel":
            execution_levels.append(str(element.attrib.get("level") or ""))

    assert "PerMonitorV2" in values.get("dpiAwareness", [])
    assert "true/pm" in values.get("dpiAware", [])
    assert "asInvoker" in execution_levels


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
    release_source = RELEASE_SCRIPT_PATH.read_text(encoding="utf-8")
    verifier_source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert release_source.count("verify_windows_exe_manifest.py") == 2
    assert "--exe $stagedExePath" in release_source
    assert "--exe $stagedPortableExePath" in release_source
    assert "RT_MANIFEST = 24" in verifier_source
    assert '"PerMonitorV2" in dpi_awareness' in verifier_source
    assert '"true/pm" in legacy_dpi_awareness' in verifier_source
    assert '"asInvoker" in execution_levels' in verifier_source
