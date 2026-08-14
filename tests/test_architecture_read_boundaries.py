"""Stable read-path architecture boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_report_and_display_reads_do_not_detect_resources() -> None:
    offenders = {
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "worktrace").rglob("*.py"))
        if "resources.detectors import detect_resource" in path.read_text(encoding="utf-8")
        and any(
            token in path.relative_to(ROOT).as_posix()
            for token in ("report", "display", "view_model", "page_read")
        )
    }
    assert not offenders


def test_read_paths_do_not_synthesize_resource_identity() -> None:
    markers = ('f"activity:{', "f'activity:{")
    for relative in (
        "worktrace/services/report_fact_query_service.py",
        "worktrace/services/resource_service.py",
    ):
        source = _source(relative)
        assert not any(marker in source for marker in markers), relative


def test_live_display_does_not_query_assignment_or_project_tables() -> None:
    markers = (
        "get_assignment_for_activity",
        "get_project(",
        "get_or_create_uncategorized_project",
    )
    for relative in (
        "worktrace/services/live_display_service.py",
        "worktrace/services/activity_display_projection.py",
    ):
        source = _source(relative)
        assert not any(marker in source for marker in markers), relative


def test_page_read_scope_is_capability_read_only() -> None:
    source = _source("worktrace/services/page_read_context.py")
    assert "PRAGMA query_only = ON" in source
    assert "conn.rollback()" in source
    assert "conn.close()" in source
    assert "conn.commit()" not in source
