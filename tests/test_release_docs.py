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
RELEASE_BUILD_PATH = REPO_ROOT / "scripts" / "build_windows_release.ps1"
RELEASE_ENV_VERIFY_PATH = REPO_ROOT / "scripts" / "verify_release_environment.py"
RELEASE_CONSTRAINTS_PATH = REPO_ROOT / "constraints-release.txt"
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


def test_release_constraints_pin_direct_windows_build_dependencies():
    constraints = _read_text(RELEASE_CONSTRAINTS_PATH)
    for pin in (
        "cryptography==49.0.0",
        "pywin32==312",
        "psutil==7.2.2",
        "openpyxl==3.1.5",
        "pywebview==6.2.1",
        "pytest==9.1.1",
        "pytest-timeout==2.4.0",
        "pyinstaller==6.21.0",
        "pillow==12.3.0",
    ):
        assert pin in constraints


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
        RELEASE_BUILD_PATH,
        RELEASE_ENV_VERIFY_PATH,
        RELEASE_CONSTRAINTS_PATH,
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
        r"dist\Trace-<version>.exe",
        r"dist\Trace-Setup-<version>.exe",
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
    assert "run_build_smoke: ${{ github.event_name == 'pull_request' }}" in standard

    for phrase in (
        'python-version: "3.11.9"',
        "pip install --disable-pip-version-check -q -r requirements-dev.txt -c constraints-release.txt",
        "constraints-release.txt",
        "python scripts/run_pytest_ci.py",
        "node --test tests/webview/*.test.js",
        "uses: ./.github/actions/build-windows-package",
        "actions/upload-artifact@v6",
        "validation-diagnostics-${{ inputs.revision }}",
        "retention-days: 3",
    ):
        assert phrase in reusable, f"reusable validation missing phrase: {phrase}"

    for phrase in (
        'python-version: "3.11.9"',
        "pip install --disable-pip-version-check -q -r requirements-dev.txt -c constraints-release.txt",
        "constraints-release.txt",
        r"scripts\build_windows_release.ps1",
        "inno-setup-6.7.3",
        '"Trace-$env:TRACE_VERSION.exe"',
        '"Trace-Setup-$env:TRACE_VERSION.exe"',
        "Unexpected release executable artifacts",
        "Release staging residue remained after the canonical build",
    ):
        assert phrase in package_action, f"package action missing phrase: {phrase}"

    assert r"dist\Trace.exe" not in package_action
    assert r"dist\Trace-Setup.exe" not in package_action
    assert "python -m PyInstaller --noconfirm --clean WorkTrace.spec" not in package_action
    assert "uses: ./.github/actions/build-windows-package" in installer
    assert "types: [labeled]" in installer
    assert "run-installer-validation" in installer
    assert r"scripts\ci\installer_runtime_smoke.ps1" in installer
    assert 'tags: ["v*"]' in installer
    assert "workflow_dispatch:" in installer
    assert "Upgrade install" in installer_runtime
    assert "Uninstall" in installer_runtime
    assert r"dist\Trace-Setup-$version.exe" in installer_runtime

    combined = "\n".join(
        (standard, reusable, package_action, installer, installer_runtime)
    )
    assert "3.12" not in combined
    assert "run_python312" not in combined


def test_local_release_build_uses_minimum_python_while_ci_remains_pinned():
    release = _read_text(RELEASE_BUILD_PATH)
    verifier = _read_text(RELEASE_ENV_VERIFY_PATH)
    readme = _read_text(README_PATH)

    assert "verify_release_environment.py" in release
    assert "--scope release" in release
    assert "minimum supported requirements" in release
    assert "MINIMUM_PYTHON_VERSION = (3, 11)" in verifier
    assert "sys.version_info" in verifier
    assert "RELEASE_PYTHON_VERSION" not in verifier
    assert "constraints-release.txt" not in verifier
    assert "importlib.metadata" not in verifier
    assert "Python 3.11+" in readme
    assert "Inno Setup 6.3.0+" in readme
