"""Stable documentation navigation and release-boundary contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CHECKLIST = ROOT / "docs" / "release-checklist.md"
VALIDATION = ROOT / "docs" / "release-validation.md"
CURRENT = ROOT / "docs" / "current-state.md"
MIGRATION = ROOT / "docs" / "ui-webview-migration.md"
AI_CONTEXT = ROOT / "docs" / "ai-context-guide.md"


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


def test_release_validation_matches_current_export_surface() -> None:
    text = _text(VALIDATION)
    assert "CSV" in text
    assert "### J. Excel Export" not in text
    assert "Excel export is unusable" not in text


def test_readme_routes_to_authoritative_docs() -> None:
    text = _text(README)
    for path in (
        "docs/current-state.md",
        "docs/history/webview-phases.md",
        "docs/ai-context-guide.md",
    ):
        assert path in text


def test_current_state_stays_concise_and_current() -> None:
    text = _text(CURRENT)
    assert len(text.splitlines()) <= 170
    assert "user project create / edit / enable-disable / archive" in text
    assert "CSV export" in text
    for term in ("Excel", "PDF", "timesheet"):
        assert term in text
    assert "history/webview-phases.md" in text


@pytest.mark.parametrize(
    "anchor",
    ["Why pywebview", "Why No React / Vite / Vue", "Why No Local HTTP Server", "worktrace.api"],
)
def test_webview_history_keeps_architecture_decision_anchors(anchor: str) -> None:
    assert anchor in _text(MIGRATION)


def test_webview_history_routes_to_current_contract_and_archive() -> None:
    text = _text(MIGRATION)
    assert "current-state.md" in text
    assert "history/webview-phases.md" in text


def test_ai_context_guide_routes_context_by_purpose() -> None:
    text = _text(AI_CONTEXT)
    lowered = text.lower()
    assert "current-state.md" in text
    assert "start here" in lowered or "default" in lowered
    assert "release-validation.md" in text
    assert "research" in lowered
    assert "not default" in lowered or "non-default" in lowered


def test_readme_limitations_keep_known_unsupported_project_rule_surface() -> None:
    readme = _text(README)
    assert "## Current Limitations" in readme
    limitations = " ".join(readme.split("## Current Limitations", 1)[1].lower().split())
    for term in ("hard delete", "backfill", "automatic rules", "batch"):
        assert term in limitations
