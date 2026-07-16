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

    return [f"line {line}: {method}" for line, method in sorted(references)]


def _remaining_test_reference_groups() -> list[tuple[str, tuple[str, ...]]]:
    project_root = Path(__file__).resolve().parents[1]
    tests_root = project_root / "tests"
    groups: list[tuple[str, tuple[str, ...]]] = []
    for path in sorted(tests_root.rglob("*.py")):
        if path == Path(__file__).resolve():
            continue
        references = tuple(_legacy_references(path))
        if references:
            groups.append((path.relative_to(project_root).as_posix(), references))
    return groups


REMAINING_TEST_REFERENCE_GROUPS = _remaining_test_reference_groups()
PARAMETERS = REMAINING_TEST_REFERENCE_GROUPS or [("no_remaining_test_references", ())]


@pytest.mark.parametrize(
    ("relative_path", "references"),
    PARAMETERS,
    ids=[relative_path for relative_path, _references in PARAMETERS],
)
def test_tests_use_test_only_activity_fact_facade(
    relative_path: str,
    references: tuple[str, ...],
) -> None:
    assert not references, (
        f"{relative_path} still uses production activity lifecycle methods:\n"
        + "\n".join(references)
    )
