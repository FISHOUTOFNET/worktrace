"""Boundary tests enforcing the UI <-> backend API contract.

The UI layer must talk to the backend exclusively through ``worktrace.api``.
Direct imports of ``worktrace.services``, ``worktrace.db`` or
``worktrace.collector`` from any module under ``worktrace/ui`` are forbidden.

Allowed UI dependencies:
- ``worktrace.api`` (the facade layer)
- ``worktrace.formatters`` / ``worktrace.constants`` (pure helpers)
- other modules inside ``worktrace.ui`` itself
- third-party and stdlib modules
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[1] / "worktrace" / "ui"

# Forbidden import statements. We match the module reference at the start of
# an import line so that ``from ..api import ...`` is not accidentally flagged
# by the ``..services`` rule.
FORBIDDEN_PATTERNS = [
    re.compile(r"^\s*from\s+\.\.services(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.services(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+\.\.db(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.db(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+\.\.collector(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.collector(\s|\.)", re.MULTILINE),
    # ``import worktrace.services`` / ``import worktrace.db`` style
    re.compile(r"^\s*import\s+worktrace\.services(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.db(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.collector(\s|$)", re.MULTILINE),
]

FORBIDDEN_LABELS = [
    "from ..services",
    "from worktrace.services",
    "from ..db",
    "from worktrace.db",
    "from ..collector",
    "from worktrace.collector",
    "import worktrace.services",
    "import worktrace.db",
    "import worktrace.collector",
]


def _collect_ui_files() -> list[Path]:
    return sorted(UI_DIR.glob("*.py"))


@pytest.fixture(scope="module")
def ui_files() -> list[Path]:
    files = _collect_ui_files()
    assert files, "expected to find UI source files under worktrace/ui"
    return files


def test_ui_directory_exists(ui_files: list[Path]) -> None:
    assert ui_files, "worktrace/ui should contain python source files"


@pytest.mark.parametrize("ui_file", _collect_ui_files(), ids=lambda p: p.name)
def test_ui_file_has_no_forbidden_backend_imports(ui_file: Path) -> None:
    source = ui_file.read_text(encoding="utf-8")
    violations: list[str] = []
    for pattern, label in zip(FORBIDDEN_PATTERNS, FORBIDDEN_LABELS):
        for match in pattern.finditer(source):
            line_no = source.count("\n", 0, match.start()) + 1
            violations.append(f"{ui_file.name}:{line_no}: {label}")
    assert not violations, (
        "UI layer must not import backend modules directly. Found forbidden imports:\n"
        + "\n".join(violations)
        + "\nUse worktrace.api.* facades instead."
    )


def test_ui_files_use_api_layer_for_backend_access(ui_files: list[Path]) -> None:
    """At least one UI file should reference the api package, otherwise the
    boundary is vacuous. This guards against the api package being silently
    removed while UI files still compile."""
    api_references = 0
    for path in ui_files:
        source = path.read_text(encoding="utf-8")
        if "worktrace.api" in source or "from ..api" in source or "from .api" in source:
            api_references += 1
    # app.py plus at least one view should talk to the api layer.
    assert api_references >= 2, (
        f"expected multiple UI files to import worktrace.api, found {api_references}"
    )
