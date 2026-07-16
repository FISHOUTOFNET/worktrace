from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY_SERVICE = ROOT / "worktrace" / "services" / "activity_service.py"

TARGET_FUNCTIONS = frozenset(
    {
        "_parse_time",
        "_duration_seconds",
        "insert_activity_row",
        "close_activity_row",
        "close_all_open_rows",
        "create_activity",
        "_close_activity_in_conn",
        "_write_resource_in_conn",
        "close_activity",
        "increment_activity_duration",
        "set_activity_duration",
        "reopen_activity",
        "apply_midnight_anchor_assignment",
        "finalize_created_activity",
    }
)


def remove_functions(source: str) -> str:
    tree = ast.parse(source, filename=str(ACTIVITY_SERVICE))
    targets = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in TARGET_FUNCTIONS
    ]
    found = {node.name for node in targets}
    missing = TARGET_FUNCTIONS - found
    if missing:
        raise RuntimeError(
            "expected legacy functions were not found: " + ", ".join(sorted(missing))
        )

    lines = source.splitlines(keepends=True)
    for node in sorted(targets, key=lambda item: item.lineno, reverse=True):
        if node.end_lineno is None:
            raise RuntimeError(f"function {node.name} has no end position")
        start = node.lineno - 1
        while start > 0 and not lines[start - 1].strip():
            start -= 1
        del lines[start : node.end_lineno]
    return "".join(lines)


def clean_imports(source: str) -> str:
    tree = ast.parse(source, filename=str(ACTIVITY_SERVICE))
    used_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    if "logging" not in used_names:
        source = source.replace("import logging\n", "", 1)
    if "datetime" not in used_names:
        source = source.replace("from datetime import datetime\n", "", 1)
    if "TIME_FORMAT" not in used_names:
        source = source.replace("    TIME_FORMAT,\n", "", 1)
    if "create_or_update_activity_resource" not in used_names:
        source = source.replace(
            "from .resource_service import attach_resource, create_or_update_activity_resource\n",
            "from .resource_service import attach_resource\n",
            1,
        )
    return source


def main() -> int:
    source = ACTIVITY_SERVICE.read_text(encoding="utf-8")
    updated = clean_imports(remove_functions(source))
    module_docstring = (
        '"""Activity queries and post-capture edits.\n\n'
        "Durable open-row lifecycle transitions are owned exclusively by\n"
        "``activity_lifecycle_service`` and ``activity_fact_repository``.\n"
        '"""\n\n'
    )
    if not updated.startswith('"""'):
        updated = module_docstring + updated
    tree = ast.parse(updated, filename=str(ACTIVITY_SERVICE))
    remaining = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in TARGET_FUNCTIONS
    }
    if remaining:
        raise RuntimeError(
            "legacy functions remain after rewrite: " + ", ".join(sorted(remaining))
        )
    ACTIVITY_SERVICE.write_text(updated, encoding="utf-8")
    print("Removed legacy activity lifecycle CRUD from activity_service.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
