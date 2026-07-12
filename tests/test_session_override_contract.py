from __future__ import annotations

from pathlib import Path


def test_legacy_session_override_production_symbols_are_absent():
    root = Path(__file__).resolve().parents[1] / "worktrace"
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.suffix in {".py", ".sql", ".js"}
    )
    assert "project_session_override" not in production
    assert "override_match_state" not in production
