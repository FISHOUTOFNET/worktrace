"""Static contracts for the single-owned activity lifecycle write boundary."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKTRACE_DIR = REPO_ROOT / "worktrace"
SERVICES_DIR = WORKTRACE_DIR / "services"
COLLECTOR_DIR = WORKTRACE_DIR / "collector"
RUNTIME_DIR = WORKTRACE_DIR / "runtime"

LEGACY_WRITE_ENTRIES = frozenset(
    {
        "insert_activity_row",
        "close_activity_row",
        "close_all_open_rows",
        "create_activity",
        "close_activity",
        "increment_activity_duration",
        "set_activity_duration",
        "reopen_activity",
        "finalize_created_activity",
        "apply_midnight_anchor_assignment",
    }
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(_read(path), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_activity_service_is_query_and_post_capture_edit_only() -> None:
    path = SERVICES_DIR / "activity_service.py"
    source = _read(path)
    definitions = _top_level_functions(path)

    assert definitions.isdisjoint(LEGACY_WRITE_ENTRIES), (
        "activity_service must not define lifecycle write entries: "
        + ", ".join(sorted(definitions & LEGACY_WRITE_ENTRIES))
    )
    for forbidden in (
        "import activity_lifecycle_service",
        "from .activity_lifecycle_service import",
        "from worktrace.services.activity_lifecycle_service import",
    ):
        assert forbidden not in source


def test_lifecycle_service_owns_repository_backed_transitions() -> None:
    source = _read(SERVICES_DIR / "activity_lifecycle_service.py")

    assert "activity_fact_repository" in source
    for required in (
        "activity_fact_repository.close_all_open_activities",
        "activity_fact_repository.insert_open_activity",
        "activity_fact_repository.close_activity",
        "activity_fact_repository.checkpoint_activity_duration",
    ):
        assert required in source
    for forbidden in (
        "activity_service.create_activity(",
        "activity_service.close_activity(",
        "activity_service.close_activity_row(",
        "activity_service.close_all_open_rows(",
        "activity_service.insert_activity_row(",
    ):
        assert forbidden not in source


def test_collector_maintenance_routes_through_atomic_seal_command() -> None:
    source = _read(COLLECTOR_DIR / "state_machine.py")
    maintenance = _read(
        SERVICES_DIR / "activity_maintenance_command_service.py"
    )

    assert "activity_maintenance_command_service.seal_open_activity_for_maintenance" in source
    assert "activity_fact_repository.close_activity" in maintenance
    assert "activity_inference_job_repository.enqueue_closed_activity_ids" in maintenance
    assert "close_all_open_activities" not in maintenance
    assert "session_boundary" not in maintenance


def test_recorder_has_no_public_midnight_split_compatibility_entrypoint() -> None:
    tree = ast.parse(
        _read(COLLECTOR_DIR / "activity_session_recorder.py"),
        filename="activity_session_recorder.py",
    )
    recorder = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ActivitySessionRecorder"
    )
    methods = {
        node.name
        for node in recorder.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "split_at_midnight" not in methods
    assert {"prepare_midnight_split", "resume_midnight_split"} <= methods


def test_runtime_routes_shutdown_close_all_through_lifecycle() -> None:
    source = _read(RUNTIME_DIR / "app_runtime.py")
    assert "activity_lifecycle_service.close_all_open_activities" in source


def test_recovery_routes_activity_and_boundary_facts_through_one_lifecycle_owner() -> None:
    source = _read(SERVICES_DIR / "recovery_service.py")
    direct_close = re.compile(
        r"UPDATE\s+activity_log\s+SET\s+end_time",
        re.IGNORECASE,
    )
    assert direct_close.search(source) is None
    assert "activity_lifecycle_service.recover_activity_batch(" in source
    assert "commands," in source
    assert "boundaries," in source
    assert "continuations," in source
    assert "activity_service.close_activity(" not in source
    assert "session_boundary_service.insert_boundary" not in source


def _legacy_activity_service_calls(path: Path) -> list[str]:
    tree = ast.parse(_read(path), filename=str(path))
    aliases: set[str] = set()
    direct_aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "worktrace.services":
                aliases.update(
                    item.asname or item.name
                    for item in node.names
                    if item.name == "activity_service"
                )
            elif node.module == "worktrace.services.activity_service":
                for item in node.names:
                    if item.name in LEGACY_WRITE_ENTRIES:
                        direct_aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.Import):
            aliases.update(
                item.asname or item.name.rsplit(".", 1)[-1]
                for item in node.names
                if item.name == "worktrace.services.activity_service"
            )

    calls: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
            and node.attr in LEGACY_WRITE_ENTRIES
        ):
            calls.add((node.lineno, node.attr))
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in direct_aliases
        ):
            calls.add((node.lineno, direct_aliases[node.id]))

    return [f"{path.relative_to(REPO_ROOT)}:{line}: {name}" for line, name in sorted(calls)]


def test_production_has_no_legacy_activity_service_write_calls() -> None:
    excluded = {
        SERVICES_DIR / "activity_service.py",
        SERVICES_DIR / "activity_lifecycle_service.py",
    }
    violations: list[str] = []
    for path in sorted(WORKTRACE_DIR.rglob("*.py")):
        if path in excluded:
            continue
        violations.extend(_legacy_activity_service_calls(path))

    assert not violations, "legacy activity write calls remain:\n" + "\n".join(violations)
