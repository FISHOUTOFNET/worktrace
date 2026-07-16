from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.unit]


LEGACY_LIFECYCLE_METHODS = frozenset(
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


def _legacy_references(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_aliases: set[str] = set()
    direct_aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "worktrace.services":
                for item in node.names:
                    if item.name == "activity_service":
                        module_aliases.add(item.asname or item.name)
            elif node.module == "worktrace.services.activity_service":
                for item in node.names:
                    if item.name in LEGACY_LIFECYCLE_METHODS:
                        direct_aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "worktrace.services.activity_service":
                    module_aliases.add(item.asname or item.name.rsplit(".", 1)[-1])

    references: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in module_aliases
            and node.attr in LEGACY_LIFECYCLE_METHODS
        ):
            references.add((node.lineno, node.attr))
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in direct_aliases
        ):
            references.add((node.lineno, direct_aliases[node.id]))

    return [
        f"{path.as_posix()}:{line}: {method}"
        for line, method in sorted(references)
    ]


def test_no_code_outside_activity_service_uses_legacy_lifecycle_methods() -> None:
    project_root = Path(__file__).resolve().parents[1]
    candidates = [
        *sorted((project_root / "worktrace").rglob("*.py")),
        *sorted((project_root / "tests").rglob("*.py")),
    ]
    excluded = {
        project_root / "worktrace" / "services" / "activity_service.py",
        Path(__file__).resolve(),
    }
    violations: list[str] = []
    for path in candidates:
        if path in excluded:
            continue
        violations.extend(_legacy_references(path))

    assert not violations, "legacy activity lifecycle references remain:\n" + "\n".join(violations)
