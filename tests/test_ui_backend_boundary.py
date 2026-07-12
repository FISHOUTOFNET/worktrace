from __future__ import annotations

from pathlib import Path
import ast

from worktrace.webview_ui.bridge import WebViewBridge


def test_bridge_exposes_projection_details_and_no_activity_id_details():
    assert hasattr(WebViewBridge, "get_timeline_session_activity_summary")
    assert not hasattr(WebViewBridge, "get_timeline_session_details")


def test_webview_never_imports_service_or_database_modules():
    root = Path(__file__).resolve().parents[1] / "worktrace" / "webview_ui"
    violations = []
    for path in root.rglob("*"):
        if path.suffix not in {".py", ".js"}:
            continue
        if path.suffix == ".js":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                "services" in str(node.module or "").split(".")
                or str(node.module or "").endswith("db")
            ):
                violations.append(str(path))
    assert violations == []


def test_public_revision_aliases_are_removed():
    root = Path(__file__).resolve().parents[1] / "worktrace"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.suffix in {".py", ".js"}
    )
    for alias in ("refresh_revision", "live_state_revision", "display_projection_revision", "page_structure_revision"):
        assert alias not in source
