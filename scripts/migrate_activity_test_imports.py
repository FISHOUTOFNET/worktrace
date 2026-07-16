from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import traceback

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


def imported_state(tree: ast.AST):
    module_aliases: dict[str, ast.ImportFrom | ast.Import] = {}
    direct_aliases: dict[str, tuple[str, ast.ImportFrom]] = {}
    facade_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "worktrace.services":
                for item in node.names:
                    if item.name == "activity_service":
                        module_aliases[item.asname or item.name] = node
            elif node.module == "worktrace.services.activity_service":
                for item in node.names:
                    if item.name in LEGACY:
                        direct_aliases[item.asname or item.name] = (item.name, node)
            elif node.module == "tests.support":
                for item in node.names:
                    if item.name == "activity_factory":
                        facade_aliases.add(item.asname or item.name)
            elif node.module == "tests.support.activity_factory":
                for item in node.names:
                    facade_aliases.add(item.asname or item.name)
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "worktrace.services.activity_service":
                    module_aliases[item.asname or item.name.rsplit(".", 1)[-1]] = node
    return module_aliases, direct_aliases, facade_aliases


def references(tree: ast.AST):
    module_aliases, direct_aliases, _ = imported_state(tree)
    refs: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in module_aliases
            and node.attr in LEGACY
        ):
            refs.append((node.lineno, node.attr))
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in direct_aliases
        ):
            refs.append((node.lineno, direct_aliases[node.id][0]))
    return sorted(set(refs))


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
    module_aliases, direct_aliases, facade_aliases = imported_state(tree)
    target_nodes = {
        node
        for node in [*module_aliases.values(), *(value[1] for value in direct_aliases.values())]
    }
    if not target_nodes:
        raise RuntimeError(f"no rewritable import found for {path}")

    lines = source.splitlines(keepends=True)
    replacements: list[tuple[int, int, str]] = []
    for node in sorted(target_nodes, key=lambda item: item.lineno):
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
                if local_name not in facade_aliases:
                    replacement_parts.append(
                        f"{indent}from tests.support import activity_factory as {local_name}\n"
                    )
                    facade_aliases.add(local_name)
            if remaining:
                replacement_parts.append(
                    render_from_import(indent, node.module, remaining)
                )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "worktrace.services.activity_service"
        ):
            legacy_items = [item for item in node.names if item.name in LEGACY]
            remaining = [item for item in node.names if item.name not in LEGACY]
            if legacy_items:
                replacement_parts.append(
                    render_from_import(
                        indent,
                        "tests.support.activity_factory",
                        legacy_items,
                    )
                )
            if remaining:
                replacement_parts.append(
                    render_from_import(indent, node.module, remaining)
                )
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
                if local_name not in facade_aliases:
                    replacement_parts.append(
                        f"{indent}from tests.support import activity_factory as {local_name}\n"
                    )
                    facade_aliases.add(local_name)
            if remaining:
                replacement_parts.append(render_plain_import(indent, remaining))
        else:
            raise RuntimeError(f"unsupported activity import in {path}:{node.lineno}")
        replacements.append(
            (node.lineno - 1, node.end_lineno, "".join(replacement_parts))
        )

    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = replacement.splitlines(keepends=True)
    path.write_text("".join(lines), encoding="utf-8")
    return True


def remaining_violations() -> list[str]:
    violations: list[str] = []
    for path in [
        *sorted((ROOT / "worktrace").rglob("*.py")),
        *sorted((ROOT / "tests").rglob("*.py")),
    ]:
        if path == ROOT / "worktrace" / "services" / "activity_service.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, method in references(tree):
            violations.append(f"{path.relative_to(ROOT).as_posix()}:{line}: {method}")
    return violations


def main() -> int:
    changed: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if migrate(path):
            changed.append(path.relative_to(ROOT).as_posix())

    violations = remaining_violations()
    if violations:
        raise RuntimeError("legacy references remain:\n" + "\n".join(violations))
    if not changed:
        raise RuntimeError("migration produced no changes")
    print("Migrated files:")
    print("\n".join(changed))
    return 0


def publish_failure_diagnostic() -> None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        return
    diagnostic_path = ROOT / "diagnostics" / "activity-fixture-migration-latest.txt"
    failure_text = "\n".join(
        (
            f"run_id={os.environ.get('GITHUB_RUN_ID', '')}",
            f"tested_head={os.environ.get('GITHUB_SHA', '')}",
            "",
            traceback.format_exc(),
        )
    )
    subprocess.run(
        ["git", "restore", "--source=HEAD", "--", "tests"],
        cwd=ROOT,
        check=True,
    )
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.write_text(failure_text, encoding="utf-8")
    subprocess.run(
        ["git", "config", "user.name", "github-actions[bot]"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["git", "add", diagnostic_path.relative_to(ROOT).as_posix()],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "Capture activity fixture migration failure [skip ci]",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "push",
            "origin",
            "HEAD:agent/canonical-architecture-consolidation",
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    try:
        exit_code = main()
    except BaseException:
        publish_failure_diagnostic()
        raise
    raise SystemExit(exit_code)
