from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "architecture_governance_allowlist.json"


def _allowlist() -> dict[str, set[str]]:
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return {name: set(paths) for name, paths in raw.items()}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _production_files() -> list[Path]:
    return sorted((ROOT / "worktrace").rglob("*.py"))


def _files_containing(token: str) -> set[str]:
    return {
        _relative(path)
        for path in _production_files()
        if token in path.read_text(encoding="utf-8")
    }


def test_governance_allowlist_paths_exist() -> None:
    for paths in _allowlist().values():
        for relative in paths:
            assert (ROOT / relative).is_file(), relative


def test_governance_allowlist_remains_empty() -> None:
    assert all(not paths for paths in _allowlist().values())


def test_report_and_display_reads_do_not_detect_resources() -> None:
    offenders = {
        path
        for path in _files_containing("resources.detectors import detect_resource")
        if any(token in path for token in ("report", "display", "view_model", "page_read"))
    }
    assert offenders <= _allowlist()["read_time_resource_detection"]


def test_read_paths_do_not_synthesize_resource_identity() -> None:
    candidates = {
        "worktrace/services/report_fact_query_service.py",
        "worktrace/services/resource_service.py",
    }
    markers = ('f"activity:{', "f'activity:{")
    offenders = {
        relative
        for relative in candidates
        if any(marker in (ROOT / relative).read_text(encoding="utf-8") for marker in markers)
    }
    assert offenders <= _allowlist()["read_time_resource_identity_fallback"]


def test_live_display_does_not_query_assignment_or_project_tables() -> None:
    candidates = {
        "worktrace/services/live_display_service.py",
        "worktrace/services/activity_display_projection.py",
    }
    markers = (
        "get_assignment_for_activity",
        "get_project(",
        "get_or_create_uncategorized_project",
    )
    offenders = {
        relative
        for relative in candidates
        if any(marker in (ROOT / relative).read_text(encoding="utf-8") for marker in markers)
    }
    assert offenders <= _allowlist()["live_project_database_fallback"]


def test_page_read_scope_is_capability_read_only() -> None:
    relative = "worktrace/services/page_read_context.py"
    source = (ROOT / relative).read_text(encoding="utf-8")
    offenders = set()
    if "PRAGMA query_only = ON" not in source:
        offenders.add(relative)
    if "conn.rollback()" not in source or "conn.close()" not in source:
        offenders.add(relative)
    if "conn.commit()" in source:
        offenders.add(relative)
    assert offenders <= _allowlist()["page_read_write_capability"]


def test_only_permanent_workflows_and_no_agent_helpers() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    workflow_names = {path.name for path in workflow_dir.glob("*.yml")}
    expected = {"_validation.yml", "ci.yml"}
    offenders = {
        _relative(path)
        for path in (ROOT / ".github").glob("agent_*.py")
    }
    if workflow_names != expected:
        offenders.update(
            f".github/workflows/{name}"
            for name in sorted(workflow_names.symmetric_difference(expected))
        )
    assert offenders <= _allowlist()["temporary_workflow_or_agent_helper"]
