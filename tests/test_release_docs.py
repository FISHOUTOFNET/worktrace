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
BUILD_DEP_CANDIDATES = [
    REPO_ROOT / "requirements-dev.txt",
    REPO_ROOT / "requirements-build.txt",
]

# documentation governance targets.
CURRENT_STATE_TARGET_LINES = 150
CURRENT_STATE_HARD_MAX_LINES = 170


def _read_text(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def _line_count(path: Path) -> int:
    return len(_read_text(path).splitlines())


# Existing release / build-dependency consistency (preserved).


def test_readme_packaging_commands_have_matching_build_dependency_file():
    """If README documents PyInstaller packaging, a build-dep file must exist."""
    readme = _read_text(README_PATH)
    mentions_pyinstaller = "PyInstaller" in readme or "WorkTrace.spec" in readme
    if not mentions_pyinstaller:
        pytest.skip("README does not reference PyInstaller packaging")

    existing = [p for p in BUILD_DEP_CANDIDATES if p.is_file()]
    assert existing, (
        "README references PyInstaller packaging but neither "
        "requirements-dev.txt nor requirements-build.txt exists"
    )


def test_build_dependency_file_includes_pyinstaller():
    """The build-dependency file must declare pyinstaller."""
    existing = [p for p in BUILD_DEP_CANDIDATES if p.is_file()]
    assert existing, "no build-dependency file (requirements-dev.txt / requirements-build.txt)"
    combined = "\n".join(_read_text(p) for p in existing)
    assert "pyinstaller" in combined.lower(), (
        "build-dependency file must include 'pyinstaller'"
    )


def test_readme_references_build_dependency_file():
    """README must point developers at the build-dependency file."""
    readme = _read_text(README_PATH)
    assert (
        "requirements-dev.txt" in readme or "requirements-build.txt" in readme
    ), "README must mention the build-dependency file name"


def test_release_checklist_exists():
    assert CHECKLIST_PATH.is_file(), "docs/release-checklist.md must exist"


def test_release_validation_doc_and_workflows_exist():
    assert VALIDATION_PATH.is_file(), "docs/release-validation.md must exist"
    for path in (CI_PATH, REUSABLE_VALIDATION_PATH):
        assert path.is_file(), f"expected permanent workflow: {path}"


def test_readme_points_to_release_validation_doc():
    readme = _read_text(README_PATH)
    assert "docs/release-validation.md" in readme


@pytest.mark.parametrize(
    "phrase",
    [
        "WorkTrace v0.1 Release Validation",
        "GitHub Actions Windows tests pass",
        r"dist\WorkTrace.exe",
        r"dist\WorkTrace-Setup.exe",
        "%LOCALAPPDATA%\\Programs\\WorkTrace",
        "Release decision: pass / blocked",
    ],
)
def test_release_validation_contains_required_baseline_items(phrase):
    validation = _read_text(VALIDATION_PATH)
    assert phrase in validation, f"release validation missing phrase: {phrase}"


def test_ci_workflows_contain_required_release_smoke_steps():
    standard = _read_text(CI_PATH)
    reusable = _read_text(REUSABLE_VALIDATION_PATH)

    assert "pull_request:" in standard
    assert "push:" in standard
    assert "./.github/workflows/_validation.yml" in standard
    assert "run_node_tests: true" in standard
    assert "run_build_smoke: true" in standard

    for phrase in (
        'python-version: "3.11"',
        "pip install --disable-pip-version-check -q -r requirements.txt",
        "python -m pytest",
        "node --test tests/webview/*.test.js",
        "python -m PyInstaller --noconfirm --clean WorkTrace.spec",
        r"scripts\build_windows_installer.ps1",
        "actions/upload-artifact@v4",
        "validation-diagnostics-${{ inputs.revision }}",
        "retention-days: 3",
    ):
        assert phrase in reusable, f"reusable validation missing phrase: {phrase}"

    combined = "\n".join((standard, reusable))
    assert "3.12" not in combined
    assert "run_python312" not in combined
    assert "acceptance.yml" not in combined


# release-checklist stub tests.


def test_current_state_doc_stays_within_governance_budget():
    line_count = _line_count(CURRENT_STATE_PATH)
    assert line_count <= CURRENT_STATE_HARD_MAX_LINES, (
        f"docs/current-state.md has {line_count} lines; "
        f"target <= {CURRENT_STATE_TARGET_LINES}, hard max {CURRENT_STATE_HARD_MAX_LINES}"
    )


def test_current_state_doc_keeps_required_sections():
    current_state = _read_text(CURRENT_STATE_PATH)
    for heading in (
        "## Current architecture",
        "## Validation commands",
        "## Known limitations",
    ):
        assert heading in current_state


def test_migration_and_ai_context_docs_exist():
    assert MIGRATION_PATH.is_file()
    assert AI_CONTEXT_PATH.is_file()
