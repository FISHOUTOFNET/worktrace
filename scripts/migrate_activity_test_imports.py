from __future__ import annotations

import ast
from pathlib import Path
import subprocess

LEGACY = frozenset(
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
ROOT = Path(__file__).resolve().parents[1]


def imported_aliases(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
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
                    if item.name in LEGACY:
                        direct_aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "worktrace.services.activity_service":
                    module_aliases.add(item.asname or item.name.rsplit(".", 1)[-1])
    return module_aliases, direct_aliases


def references(tree: ast.AST) -> list[tuple[int, str]]:
    module_aliases, direct_aliases = imported_aliases(tree)
    refs: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in module_aliases
            and node.attr in LEGACY
        ):
            refs.add((node.lineno, node.attr))
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in direct_aliases
        ):
            refs.add((node.lineno, direct_aliases[node.id]))
    return sorted(refs)


def target_import_nodes(tree: ast.AST) -> list[ast.ImportFrom | ast.Import]:
    targets: list[ast.ImportFrom | ast.Import] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "worktrace.services" and any(
                item.name == "activity_service" for item in node.names
            ):
                targets.append(node)
            elif node.module == "worktrace.services.activity_service" and any(
                item.name in LEGACY for item in node.names
            ):
                targets.append(node)
        elif isinstance(node, ast.Import) and any(
            item.name == "worktrace.services.activity_service" for item in node.names
        ):
            targets.append(node)
    return sorted(targets, key=lambda item: item.lineno)


def alias_text(item: ast.alias) -> str:
    return item.name + (f" as {item.asname}" if item.asname else "")


def render_from_import(indent: str, module: str, names: list[ast.alias]) -> str:
    rendered = [alias_text(item) for item in names]
    if len(rendered) == 1:
        return f"{indent}from {module} import {rendered[0]}\n"
    body = "".join(f"{indent}    {name},\n" for name in rendered)
    return f"{indent}from {module} import (\n{body}{indent})\n"


def render_plain_import(indent: str, names: list[ast.alias]) -> str:
    return f"{indent}import {', '.join(alias_text(item) for item in names)}\n"


def migrate(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    if not references(tree):
        return False
    targets = target_import_nodes(tree)
    if not targets:
        raise RuntimeError(f"no rewritable import found for {path}")

    lines = source.splitlines(keepends=True)
    replacements: list[tuple[int, int, str]] = []
    for node in targets:
        if node.end_lineno is None:
            raise RuntimeError(f"import has no end position in {path}:{node.lineno}")
        indent = lines[node.lineno - 1][
            : len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())
        ]
        replacement_parts: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module == "worktrace.services":
            activity_items = [item for item in node.names if item.name == "activity_service"]
            remaining = [item for item in node.names if item.name != "activity_service"]
            for item in activity_items:
                local_name = item.asname or item.name
                replacement_parts.append(
                    f"{indent}from tests.support import activity_factory as {local_name}\n"
                )
            if remaining:
                replacement_parts.append(render_from_import(indent, node.module, remaining))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "worktrace.services.activity_service"
        ):
            legacy_items = [item for item in node.names if item.name in LEGACY]
            remaining = [item for item in node.names if item.name not in LEGACY]
            if legacy_items:
                replacement_parts.append(
                    render_from_import(indent, "tests.support.activity_factory", legacy_items)
                )
            if remaining:
                replacement_parts.append(render_from_import(indent, node.module, remaining))
        elif isinstance(node, ast.Import):
            activity_items = [
                item
                for item in node.names
                if item.name == "worktrace.services.activity_service"
            ]
            remaining = [
                item
                for item in node.names
                if item.name != "worktrace.services.activity_service"
            ]
            for item in activity_items:
                local_name = item.asname or item.name.rsplit(".", 1)[-1]
                replacement_parts.append(
                    f"{indent}from tests.support import activity_factory as {local_name}\n"
                )
            if remaining:
                replacement_parts.append(render_plain_import(indent, remaining))
        else:
            raise RuntimeError(f"unsupported activity import in {path}:{node.lineno}")
        replacements.append(
            (node.lineno - 1, node.end_lineno, "".join(replacement_parts))
        )

    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = replacement.splitlines(keepends=True)
    migrated = "".join(lines)
    ast.parse(migrated, filename=str(path))
    path.write_text(migrated, encoding="utf-8")
    return True


def remaining_test_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, method in references(tree):
            violations.append(f"{path.relative_to(ROOT).as_posix()}:{line}: {method}")
    return violations


def remove_temporary_ci_job() -> None:
    workflow = ROOT / ".github" / "workflows" / "ci.yml"
    source = workflow.read_text(encoding="utf-8")
    start_marker = "  activity-fixture-migration:\n"
    tests_marker = "  tests:\n"
    start = source.find(start_marker)
    end = source.find(tests_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise RuntimeError("temporary activity fixture migration job was not found")
    source = source[:start] + source[end:]
    temporary_if = (
        "    if: github.event_name != 'pull_request' || "
        "github.event.pull_request.head.ref != "
        "'agent/canonical-architecture-consolidation'\n"
    )
    if temporary_if not in source:
        raise RuntimeError("temporary tests job condition was not found")
    source = source.replace(temporary_if, "", 1)
    workflow.write_text(source, encoding="utf-8")


def stage_one_shot_changes() -> None:
    subprocess.run(
        ["git", "add", "tests", ".github/workflows/ci.yml"],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    changed: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if migrate(path):
            changed.append(path.relative_to(ROOT).as_posix())

    violations = remaining_test_violations()
    if violations:
        raise RuntimeError("test lifecycle references remain:\n" + "\n".join(violations))
    if not changed:
        raise RuntimeError("migration produced no changes")

    remove_temporary_ci_job()
    stage_one_shot_changes()
    print("Migrated files:")
    print("\n".join(changed))
    print("Removed temporary activity fixture migration job")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
