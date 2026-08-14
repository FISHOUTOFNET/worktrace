"""Operational release-documentation contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "docs" / "release-checklist.md"
VALIDATION = ROOT / "docs" / "release-validation.md"


def _text(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def test_release_docs_have_one_canonical_checklist() -> None:
    checklist = _text(CHECKLIST)
    assert "docs/release-validation.md" in checklist
    assert "canonical" in checklist.lower()


@pytest.mark.parametrize(
    "command",
    [
        'python -m pytest -m "not benchmark"',
        "python -m worktrace.main",
        "python -m PyInstaller --noconfirm --clean WorkTrace.spec",
        r"scripts\build_windows_installer.ps1",
    ],
)
def test_release_validation_keeps_executable_commands(command: str) -> None:
    assert command in _text(VALIDATION)


@pytest.mark.parametrize("phrase", ["不截屏", "不录屏", "不记录键盘", "不上传数据", "排除规则"])
def test_release_validation_keeps_privacy_acceptance(phrase: str) -> None:
    assert phrase in _text(VALIDATION)
