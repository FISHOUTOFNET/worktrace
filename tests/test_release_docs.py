"""Release documentation / build-dependency consistency tests.

These tests guard against drift between README build instructions, the
build-dependency file, and the release validation baseline. They also lock
the documentation governance rules so the docs do not re-bloat.

They are intentionally cross-platform: they only read text files and never
invoke PyInstaller, start the UI, or require Windows.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.parallel_safe]

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"
CHECKLIST_PATH = REPO_ROOT / "docs" / "release-checklist.md"
VALIDATION_PATH = REPO_ROOT / "docs" / "release-validation.md"
CURRENT_STATE_PATH = REPO_ROOT / "docs" / "current-state.md"
MIGRATION_PATH = REPO_ROOT / "docs" / "ui-webview-migration.md"
AI_CONTEXT_PATH = REPO_ROOT / "docs" / "ai-context-guide.md"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
CI_PATH = WORKFLOW_DIR / "ci.yml"
REUSABLE_VALIDATION_PATH = WORKFLOW_DIR / "_validation.yml"
INSTALLER_VALIDATION_PATH = WORKFLOW_DIR / "installer-validation.yml"
PACKAGE_ACTION_PATH = (
    REPO_ROOT / ".github" / "actions" / "build-windows-package" / "action.yml"
)
INSTALLER_RUNTIME_SMOKE_PATH = (
    REPO_ROOT / "scripts" / "ci" / "installer_runtime_smoke.ps1"
)
ACCEPTANCE_PATH = WORKFLOW_DIR / "acceptance.yml"
BUILD_DEP_CANDIDATES = [
    REPO_ROOT / "requirements-dev.txt",
    REPO_ROOT / "requirements-build.txt",
]

CURRENT_STATE_TARGET_LINES = 150
CURRENT_STATE_HARD_MAX_LINES = 170


def _read_text(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def _line_count(path: Path) -> int:
    return len(_read_text(path).splitlines())


def test_readme_packaging_commands_have_matching_build_dependency_file():
    readme = _read_text(README_PATH)
    mentions_pyinstaller = "PyInstaller" in readme or "WorkTrace.spec" in readme
    if not mentions_pyinstaller:
        pytest.skip("README does not reference PyInstaller packaging")
    existing = [p for p in BUILD_DEP_CANDIDATES if p.is_file()]
    assert existing


def test_build_dependency_file_includes_pyinstaller():
    existing = [p for p in BUILD_DEP_CANDIDATES if p.is_file()]
    assert existing
    combined = "\n".join(_read_text(p) for p in existing)
    assert "pyinstaller" in combined.lower()


def test_readme_references_build_dependency_file():
    readme = _read_text(README_PATH)
    assert "requirements-dev.txt" in readme or "requirements-build.txt" in readme


def test_release_checklist_exists():
    assert CHECKLIST_PATH.is_file()


def test_release_validation_doc_and_workflows_exist():
    assert VALIDATION_PATH.is_file()
    for path in (
        CI_PATH,
        REUSABLE_VALIDATION_PATH,
        INSTALLER_VALIDATION_PATH,
        PACKAGE_ACTION_PATH,
        INSTALLER_RUNTIME_SMOKE_PATH,
    ):
        assert path.is_file()
    assert not ACCEPTANCE_PATH.exists()


def test_readme_points_to_release_validation_doc():
    assert "docs/release-validation.md" in _read_text(README_PATH)


@pytest.mark.parametrize(
    "phrase",
    [
        "有迹 (Trace) v0.1 Release Validation",
        "GitHub Actions Windows tests pass",
        r"dist\Trace.exe",
        r"dist\Trace-Setup.exe",
        "%LOCALAPPDATA%\\Programs\\Trace",
        "Release decision: pass / blocked",
    ],
)
def test_release_validation_contains_required_baseline_items(phrase):
    validation = _read_text(VALIDATION_PATH)
    assert phrase in validation, f"release validation missing phrase: {phrase}"


def test_ci_layers_contain_required_release_smoke_steps():
    standard = _read_text(CI_PATH)
    reusable = _read_text(REUSABLE_VALIDATION_PATH)
    package_action = _read_text(PACKAGE_ACTION_PATH)
    installer = _read_text(INSTALLER_VALIDATION_PATH)
    installer_runtime = _read_text(INSTALLER_RUNTIME_SMOKE_PATH)

    assert "pull_request:" in standard
    assert "push:" in standard
    assert "./.github/workflows/_validation.yml" in standard
    assert "run_node_tests: true" in standard
    assert "run_build_smoke: true" in standard

    for phrase in (
        'python-version: "3.11"',
        "pip install --disable-pip-version-check -q -r requirements-dev.txt",
        "python scripts/run_pytest_ci.py",
        "node --test tests/webview/*.test.js",
        "uses: ./.github/actions/build-windows-package",
        "actions/upload-artifact@v6",
        "validation-diagnostics-${{ inputs.revision }}",
        "retention-days: 3",
    ):
        assert phrase in reusable, f"reusable validation missing phrase: {phrase}"

    for phrase in (
        'python-version: "3.11"',
        "pip install --disable-pip-version-check -q -r requirements-dev.txt",
        "python -m PyInstaller --noconfirm --clean WorkTrace.spec",
        r"scripts\build_windows_installer.ps1",
        r"dist\Trace.exe",
        r"dist\Trace-Setup.exe",
    ):
        assert phrase in package_action, f"package action missing phrase: {phrase}"

    assert "uses: ./.github/actions/build-windows-package" in installer
    assert r"scripts\ci\installer_runtime_smoke.ps1" in installer
    assert 'tags: ["v*"]' in installer
    assert "workflow_dispatch:" in installer
    assert "Upgrade install" in installer_runtime
    assert "Uninstall" in installer_runtime

    combined = "\n".join(
        (standard, reusable, package_action, installer, installer_runtime)
    )
    assert "3.12" not in combined
    assert "run_python312" not in combined
