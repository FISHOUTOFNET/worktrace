"""Release documentation / build-dependency consistency tests.

These tests guard against drift between README build instructions, the
build-dependency file, and the release checklist. They are intentionally
cross-platform: they only read text files and never invoke PyInstaller,
start the UI, or require Windows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"
CHECKLIST_PATH = REPO_ROOT / "docs" / "release-checklist.md"
BUILD_DEP_CANDIDATES = [
    REPO_ROOT / "requirements-dev.txt",
    REPO_ROOT / "requirements-build.txt",
]


def _read_text(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


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


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        "python -m worktrace.main",
        "python -m PyInstaller --noconfirm --clean WorkTrace.spec",
        r"scripts\build_windows_installer.ps1",
    ],
)
def test_release_checklist_contains_key_command(command):
    checklist = _read_text(CHECKLIST_PATH)
    assert command in checklist, f"release checklist missing command: {command}"


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
def test_release_checklist_contains_privacy_acceptance_phrase(phrase):
    checklist = _read_text(CHECKLIST_PATH)
    assert phrase in checklist, f"release checklist missing privacy phrase: {phrase}"
