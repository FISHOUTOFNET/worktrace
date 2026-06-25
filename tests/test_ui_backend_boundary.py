"""Boundary tests enforcing the UI <-> backend API contract.

The UI layer must talk to the backend exclusively through ``worktrace.api``.
Direct imports of ``worktrace.services``, ``worktrace.db``,
``worktrace.collector``, or ``worktrace.security`` from any module under
``worktrace/ui`` are forbidden.

The same boundary applies to the WebView UI package
``worktrace/webview_ui`` (the default and only shipping UI as of Phase 1).
In addition, the WebView bridge (``bridge.py``) must not import
``worktrace.runtime`` or ``worktrace.config`` either: it may only reach the
backend through ``worktrace.api``. The WebView entry point
(``worktrace/webview_main.py``) is allowed to import ``AppRuntime``,
``config``, and ``db`` initialization helpers, mirroring ``worktrace/main.py``,
but still must not import ``services``, ``collector``, or ``security``.

The legacy ``worktrace/ui`` (Tkinter / CustomTkinter) package is retained in
the source tree as legacy code pending removal, not as a supported runtime
path. Its boundary rules are still enforced so it cannot become a backdoor
into the backend while it remains in the tree.

Allowed UI / WebView dependencies:
- ``worktrace.api`` (the facade layer)
- ``worktrace.formatters`` / ``worktrace.constants`` (pure helpers)
- other modules inside ``worktrace.ui`` / ``worktrace.webview_ui`` itself
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
    re.compile(r"^\s*from\s+\.\.security(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.security(\s|\.)", re.MULTILINE),
    # ``import worktrace.services`` / ``import worktrace.db`` style
    re.compile(r"^\s*import\s+worktrace\.services(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.db(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.collector(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.security(\s|$)", re.MULTILINE),
]

FORBIDDEN_LABELS = [
    "from ..services",
    "from worktrace.services",
    "from ..db",
    "from worktrace.db",
    "from ..collector",
    "from worktrace.collector",
    "from ..security",
    "from worktrace.security",
    "import worktrace.services",
    "import worktrace.db",
    "import worktrace.collector",
    "import worktrace.security",
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


# ---------------------------------------------------------------------------
# WebView UI boundary tests
# ---------------------------------------------------------------------------

WEBVIEW_UI_DIR = Path(__file__).resolve().parents[1] / "worktrace" / "webview_ui"

# The bridge module has stricter rules: no runtime, no config, no db either.
BRIDGE_FORBIDDEN_PATTERNS = FORBIDDEN_PATTERNS + [
    re.compile(r"^\s*from\s+\.\.runtime(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.runtime(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+\.\.config(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*from\s+worktrace\.config(\s|\.)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.runtime(\s|$)", re.MULTILINE),
    re.compile(r"^\s*import\s+worktrace\.config(\s|$)", re.MULTILINE),
]

BRIDGE_FORBIDDEN_LABELS = FORBIDDEN_LABELS + [
    "from ..runtime",
    "from worktrace.runtime",
    "from ..config",
    "from worktrace.config",
    "import worktrace.runtime",
    "import worktrace.config",
]


def _collect_webview_ui_files() -> list[Path]:
    if not WEBVIEW_UI_DIR.is_dir():
        return []
    return sorted(WEBVIEW_UI_DIR.glob("*.py"))


@pytest.fixture(scope="module")
def webview_ui_files() -> list[Path]:
    return _collect_webview_ui_files()


def test_webview_ui_directory_exists() -> None:
    assert WEBVIEW_UI_DIR.is_dir(), (
        "worktrace/webview_ui directory must exist (Phase 1 default UI package)"
    )


def test_webview_ui_has_init() -> None:
    assert (WEBVIEW_UI_DIR / "__init__.py").is_file(), (
        "worktrace/webview_ui/__init__.py must exist"
    )


@pytest.mark.parametrize(
    "wv_file",
    _collect_webview_ui_files(),
    ids=lambda p: f"webview/{p.name}",
)
def test_webview_ui_file_has_no_forbidden_backend_imports(wv_file: Path) -> None:
    """All webview_ui modules must not import services/db/collector/security."""
    source = wv_file.read_text(encoding="utf-8")
    violations: list[str] = []
    for pattern, label in zip(FORBIDDEN_PATTERNS, FORBIDDEN_LABELS):
        for match in pattern.finditer(source):
            line_no = source.count("\n", 0, match.start()) + 1
            violations.append(f"webview/{wv_file.name}:{line_no}: {label}")
    assert not violations, (
        "WebView UI layer must not import backend modules directly. "
        "Found forbidden imports:\n"
        + "\n".join(violations)
        + "\nUse worktrace.api.* facades instead."
    )


def test_webview_bridge_has_no_runtime_or_config_imports() -> None:
    """The bridge module must only use worktrace.api, not runtime/config/db."""
    bridge_path = WEBVIEW_UI_DIR / "bridge.py"
    if not bridge_path.is_file():
        pytest.skip("bridge.py not implemented yet (Phase 1)")
    source = bridge_path.read_text(encoding="utf-8")
    violations: list[str] = []
    for pattern, label in zip(BRIDGE_FORBIDDEN_PATTERNS, BRIDGE_FORBIDDEN_LABELS):
        for match in pattern.finditer(source):
            line_no = source.count("\n", 0, match.start()) + 1
            violations.append(f"webview/bridge.py:{line_no}: {label}")
    assert not violations, (
        "WebView bridge must not import runtime, config, services, db, "
        "collector, or security. Found forbidden imports:\n"
        + "\n".join(violations)
        + "\nUse worktrace.api.* facades instead."
    )


def test_webview_ui_uses_api_layer(webview_ui_files: list[Path]) -> None:
    """Once bridge.py is implemented, at least one webview_ui file should
    reference worktrace.api. This test is soft: it passes vacuously until
    bridge.py is added."""
    if not webview_ui_files:
        pytest.skip("no webview_ui source files yet")
    api_references = 0
    for path in webview_ui_files:
        source = path.read_text(encoding="utf-8")
        if "worktrace.api" in source or "from ..api" in source or "from .api" in source:
            api_references += 1
    # Once bridge.py exists, it should reference the api layer.
    has_bridge = any(p.name == "bridge.py" for p in webview_ui_files)
    if has_bridge:
        assert api_references >= 1, (
            "expected bridge.py to import worktrace.api, found 0 api references"
        )


def test_webview_frontend_resources_have_no_external_links() -> None:
    """WebView frontend resources must not contain http://, https://, CDN,
    or Google Fonts references."""
    resource_dir = WEBVIEW_UI_DIR / "static"
    if not resource_dir.is_dir():
        pytest.skip("static/ resource directory not created yet (Phase 1)")
    forbidden_patterns = [
        re.compile(r'https?://', re.IGNORECASE),
        re.compile(r'cdn', re.IGNORECASE),
        re.compile(r'google\s*fonts', re.IGNORECASE),
    ]
    violations: list[str] = []
    for res_file in sorted(resource_dir.rglob("*")):
        if not res_file.is_file():
            continue
        if res_file.suffix.lower() not in (".html", ".css", ".js", ".json"):
            continue
        try:
            source = res_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in forbidden_patterns:
            for match in pattern.finditer(source):
                line_no = source.count("\n", 0, match.start()) + 1
                rel = res_file.relative_to(WEBVIEW_UI_DIR)
                violations.append(
                    f"static/{rel}:{line_no}: {match.group().strip()!r}"
                )
    assert not violations, (
        "WebView frontend resources must not contain external links, "
        "CDN, or Google Fonts references. Found:\n"
        + "\n".join(violations)
    )
