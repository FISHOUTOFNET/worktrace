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

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"
CHECKLIST_PATH = REPO_ROOT / "docs" / "release-checklist.md"
VALIDATION_PATH = REPO_ROOT / "docs" / "release-validation.md"
CURRENT_STATE_PATH = REPO_ROOT / "docs" / "current-state.md"
MIGRATION_PATH = REPO_ROOT / "docs" / "ui-webview-migration.md"
AI_CONTEXT_PATH = REPO_ROOT / "docs" / "ai-context-guide.md"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
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


# ---------------------------------------------------------------------------
# Existing release / build-dependency consistency (preserved).
# ---------------------------------------------------------------------------


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


def test_release_validation_doc_and_ci_workflow_exist():
    assert VALIDATION_PATH.is_file(), "docs/release-validation.md must exist"
    assert CI_PATH.is_file(), ".github/workflows/ci.yml must exist"


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


@pytest.mark.parametrize(
    "phrase",
    [
        "runs-on: windows-latest",
        'python-version: ["3.11", "3.12"]',
        "pip install -r requirements.txt",
        "pytest",
        "python -m PyInstaller --noconfirm --clean WorkTrace.spec",
        r"scripts\build_windows_installer.ps1",
        "actions/upload-artifact@v4",
    ],
)
def test_ci_workflow_contains_required_release_smoke_steps(phrase):
    workflow = _read_text(CI_PATH)
    assert phrase in workflow, f"CI workflow missing phrase: {phrase}"


# ---------------------------------------------------------------------------
# release-checklist stub tests.
# ---------------------------------------------------------------------------


def test_release_checklist_points_to_release_validation():
    """release-checklist.md is now a stub; it must point to release-validation."""
    checklist = _read_text(CHECKLIST_PATH)
    assert "docs/release-validation.md" in checklist, (
        "release-checklist.md must point to docs/release-validation.md"
    )
    assert "canonical" in checklist.lower(), (
        "release-checklist.md must say release-validation is the canonical baseline"
    )


@pytest.mark.parametrize(
    "section",
    [
        "Release Blockers",
        "Packaging Test",
        "Installer Test",
        "Core Functional Manual Test",
    ],
)
def test_release_checklist_does_not_contain_full_checklist_sections(section):
    """release-checklist.md must not retain full checklist sections."""
    checklist = _read_text(CHECKLIST_PATH)
    assert section not in checklist, (
        f"release-checklist.md must not contain full checklist section: {section}"
    )


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        "python -m worktrace.main",
        "python -m PyInstaller --noconfirm --clean WorkTrace.spec",
        r"scripts\build_windows_installer.ps1",
    ],
)
def test_release_validation_contains_key_command(command):
    """Release-validation owns the canonical release commands."""
    validation = _read_text(VALIDATION_PATH)
    assert command in validation, f"release validation missing command: {command}"


@pytest.mark.parametrize(
    "phrase",
    [
        "不截屏",
        "不录屏",
        "不记录键盘",
        "不上传数据",
        "排除规则",
    ],
)
def test_release_validation_contains_privacy_acceptance_phrase(phrase):
    """Release-validation owns the canonical privacy validation phrases."""
    validation = _read_text(VALIDATION_PATH)
    assert phrase in validation, f"release validation missing privacy phrase: {phrase}"


# ---------------------------------------------------------------------------
# CSV-only release doc test.
# ---------------------------------------------------------------------------


def test_release_validation_contains_csv_export():
    validation = _read_text(VALIDATION_PATH)
    assert "CSV export" in validation, (
        "release-validation.md must contain 'CSV export'"
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "### J. Excel Export",
        "Summary sheet exists",
        "Activity Logs sheet exists",
        "Exported file opens in Excel",
        "Excel export is unusable",
    ],
)
def test_release_validation_does_not_contain_positive_excel_acceptance(phrase):
    """Positive Excel export acceptance phrases must not appear; CSV is the
    only export format. References stating Excel / PDF / timesheet export are
    unsupported are allowed."""
    validation = _read_text(VALIDATION_PATH)
    assert phrase not in validation, (
        f"release-validation.md must not contain positive Excel acceptance: {phrase}"
    )


# ---------------------------------------------------------------------------
# README doc diet tests.
# ---------------------------------------------------------------------------


def test_readme_points_to_current_state():
    readme = _read_text(README_PATH)
    assert "docs/current-state.md" in readme, (
        "README Current state block must point to docs/current-state.md"
    )


def test_readme_points_to_history():
    readme = _read_text(README_PATH)
    assert "docs/history/webview-phases.md" in readme, (
        "README must point to docs/history/webview-phases.md for phase history"
    )


def test_readme_points_to_ai_context_guide():
    readme = _read_text(README_PATH)
    assert "docs/ai-context-guide.md" in readme, (
        "README must point to docs/ai-context-guide.md"
    )


@pytest.mark.parametrize(
    "phase_label",
    [
        "5B.1",
        "5C.1",
        "5D.1",
        "5E.1",
    ],
)
def test_readme_does_not_contain_project_rules_phase_chronology(phase_label):
    """README must not carry long Project Rules phase-by-phase chronology."""
    readme = _read_text(README_PATH)
    assert phase_label not in readme, (
        f"README must not contain per-phase Project Rules chronology: {phase_label}"
    )


# ---------------------------------------------------------------------------
# current-state one-screen test.
# ---------------------------------------------------------------------------


def test_current_state_line_count_under_hard_max():
    """docs/current-state.md must stay within the one-screen hard max."""
    count = _line_count(CURRENT_STATE_PATH)
    assert count <= CURRENT_STATE_HARD_MAX_LINES, (
        f"docs/current-state.md is {count} lines; hard max is "
        f"{CURRENT_STATE_HARD_MAX_LINES}. Target is {CURRENT_STATE_TARGET_LINES}."
    )


def test_current_state_documents_project_rules_lifecycle():
    """Post-WebView-migration: current-state.md no longer carries UI
    migration phase labels. Instead it must document the
    shipped capability — user project create / edit / enable-disable /
    archive — which is what the old phase label was a proxy for."""
    text = _read_text(CURRENT_STATE_PATH)
    assert "automatic rules" not in text, (
        "current-state.md must not carry UI migration phase labels "
        "(post-migration governance)"
    )
    assert "user project create / edit / enable-disable / archive" in text, (
        "current-state.md must document user project create / edit / "
        "enable-disable / archive as shipped capabilities"
    )


def test_current_state_contains_csv_export():
    text = _read_text(CURRENT_STATE_PATH)
    assert "CSV export" in text, "current-state.md must mention CSV export"


def test_current_state_contains_unsupported_excel_pdf_timesheet():
    text = _read_text(CURRENT_STATE_PATH)
    for term in ("Excel", "PDF", "timesheet"):
        assert term in text, (
            f"current-state.md must list {term} export as unsupported"
        )


def test_current_state_points_to_history():
    text = _read_text(CURRENT_STATE_PATH)
    assert "history/webview-phases.md" in text, (
        "current-state.md must point to docs/history/webview-phases.md"
    )


def test_current_state_retains_affected_test_command():
    text = _read_text(CURRENT_STATE_PATH)
    assert "python scripts/run_affected_tests.py" in text, (
        "current-state.md must retain the day-to-day affected-test command"
    )


# ---------------------------------------------------------------------------
# ui-webview-migration slimness test.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "anchor",
    [
        "Why pywebview",
        "Why No React / Vite / Vue",
        "Why No Local HTTP Server",
        "worktrace.api",
    ],
)
def test_ui_webview_migration_contains_architecture_anchors(anchor):
    text = _read_text(MIGRATION_PATH)
    assert anchor in text, (
        f"ui-webview-migration.md must retain architecture decision anchor: {anchor}"
    )


def test_ui_webview_migration_points_to_current_state_and_history():
    text = _read_text(MIGRATION_PATH)
    assert "current-state.md" in text, (
        "ui-webview-migration.md must point to current-state.md"
    )
    assert "history/webview-phases.md" in text, (
        "ui-webview-migration.md must point to history/webview-phases.md"
    )


def test_ui_webview_migration_status_section_has_no_phase_5g_facades():
    """The Status section must not carry detailed API facade names."""
    text = _read_text(MIGRATION_PATH)
    status_section = text.split("## Status", 1)[1].split("## ", 1)[0]
    for facade in (
        "create_project_for_rules",
        "update_project_for_rules",
        "archive_project_for_rules",
    ):
        assert facade not in status_section, (
            f"ui-webview-migration.md Status section must not contain 5G "
            f"facade name: {facade}"
        )


# ---------------------------------------------------------------------------
# AI context governance test.
# ---------------------------------------------------------------------------


def test_ai_context_guide_marks_current_state_as_default_reading_source():
    text = _read_text(AI_CONTEXT_PATH)
    assert "current-state.md" in text, (
        "ai-context-guide.md must mention current-state.md as a default reading source"
    )
    assert "Start here" in text or "default" in text.lower(), (
        "ai-context-guide.md must mark current-state as the default start source"
    )


def test_ai_context_guide_says_readme_and_history_not_default_read():
    text = _read_text(AI_CONTEXT_PATH)
    assert "not" in text.lower() and "default-read" in text.lower(), (
        "ai-context-guide.md must state README and history are not default-read"
    )


def test_ai_context_guide_marks_release_validation_as_release_only():
    text = _read_text(AI_CONTEXT_PATH)
    assert "release-validation.md" in text, (
        "ai-context-guide.md must mention release-validation.md"
    )
    assert "release" in text.lower(), (
        "ai-context-guide.md must mark release-validation as release-only"
    )


def test_ai_context_guide_marks_research_docs_as_non_default_context():
    text = _read_text(AI_CONTEXT_PATH)
    assert "research" in text.lower(), (
        "ai-context-guide.md must mention research docs"
    )
    assert "not default context" in text.lower() or "non-default" in text.lower(), (
        "ai-context-guide.md must mark research docs as non-default context"
    )


# ---------------------------------------------------------------------------
# README Current Limitations residual contradiction regression.
# ---------------------------------------------------------------------------

# Project Rules capabilities that the current-state capability matrix lists
# as SUPPORTED. The README Current Limitations section must NOT list any of
# these as unsupported, otherwise the two docs contradict each other.
_SUPPORTED_PROJECT_RULES_CAPABILITIES = (
    "Project enable/disable",
    "Project create/edit/archive",
    "Project create/edit/delete/archive",
)


def _readme_current_limitations_section() -> str:
    """Return the README Current Limitations section body (lowercased,
    with runs of whitespace collapsed to single spaces so wrapped-line
    substring contracts do not spuriously fail)."""
    readme = _read_text(README_PATH)
    assert "## Current Limitations" in readme, (
        "README must contain a Current Limitations section"
    )
    body = readme.split("## Current Limitations", 1)[1]
    # Stop at the next top-level section.
    body = body.split("\n## ", 1)[0]
    return " ".join(body.lower().split())


@pytest.mark.parametrize("phrase", _SUPPORTED_PROJECT_RULES_CAPABILITIES)
def test_readme_current_limitations_does_not_list_supported_project_rules_as_unsupported(phrase):
    """README Current Limitations must not list Project Rules capabilities
    that the current-state matrix marks as supported (project enable/disable,
    project create/edit/archive) as unsupported. This is the DG1.1
    regression that prevents the DG1 residual contradiction from coming back.
    """
    limitations = _readme_current_limitations_section()
    assert phrase.lower() not in limitations, (
        f"README Current Limitations must not list supported Project Rules "
        f"capability as unsupported: {phrase}"
    )


def test_readme_current_limitations_lists_genuinely_unsupported_project_rules():
    """README Current Limitations must still call out the genuinely
    unsupported Project Rules capabilities so the boundary stays explicit."""
    limitations = _readme_current_limitations_section()
    for term in ("hard delete", "backfill", "automatic rules", "batch"):
        assert term in limitations, (
            f"README Current Limitations must mention genuinely unsupported "
            f"Project Rules term: {term}"
        )


def test_readme_points_to_current_state_history_and_ai_context_after_dg1_1():
    """Single combined regression: README must still point at all three
    governance docs after the DG1.1 fix (guards against accidental deletion
    of the pointer block during a future edit)."""
    readme = _read_text(README_PATH)
    for doc in (
        "docs/current-state.md",
        "docs/history/webview-phases.md",
        "docs/ai-context-guide.md",
    ):
        assert doc in readme, (
            f"README must point at governance doc after DG1.1: {doc}"
        )


def test_current_state_remains_under_one_screen_hard_max_after_dg1_1():
    """DG1.1 must not bloat current-state.md past the one-screen hard max."""
    count = _line_count(CURRENT_STATE_PATH)
    assert count <= CURRENT_STATE_HARD_MAX_LINES, (
        f"docs/current-state.md is {count} lines after DG1.1; hard max is "
        f"{CURRENT_STATE_HARD_MAX_LINES}."
    )


def test_current_state_phase_description_is_unambiguous_after_dg1_1():
    """The description must use unambiguous wording that lists
    user project create / edit / enable-disable / archive as distinct
    capabilities — not the old "on existing user projects" form that could
    be misread as "create only on existing user projects"."""
    text = _read_text(CURRENT_STATE_PATH)
    assert "user project create / edit / enable-disable / archive" in text, (
        "current-state.md must list user project create / edit / enable-disable "
        "/ archive as distinct capabilities (unambiguous wording)"
    )
    assert "on existing user projects" not in text, (
        "current-state.md must not retain the DG1.1-removed ambiguous wording "
        "'on existing user projects'"
    )
