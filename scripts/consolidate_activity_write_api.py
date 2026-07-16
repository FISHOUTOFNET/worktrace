from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import traceback

SELF = Path("scripts/consolidate_activity_write_api.py")
WORKFLOW = Path(".github/workflows/consolidate-activity-write-api.yml")
DIAGNOSTIC = Path("diagnostics/activity-write-api-consolidation-error.txt")
ALIASES = {
    "create_activity": "insert_activity_row",
    "close_activity": "close_activity_row",
    "close_all_open_activities": "close_all_open_rows",
}
REMOVE_FUNCTIONS = {
    "create_activity",
    "close_activity",
    "close_all_open_activities",
    "increment_activity_duration",
    "reopen_activity",
}


def remove_functions(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    spans: list[tuple[int, int]] = []
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in REMOVE_FUNCTIONS:
            found.add(node.name)
            start = node.lineno - 1
            while start > 0 and lines[start - 1].strip() == "":
                start -= 1
            spans.append((start, node.end_lineno))
    missing = REMOVE_FUNCTIONS - found
    if missing:
        raise RuntimeError(f"activity_service functions not found: {sorted(missing)}")
    for start, end in sorted(spans, reverse=True):
        del lines[start:end]
    text = "".join(lines)
    if not text.startswith('"""'):
        text = (
            '"""Low-level activity fact repository helpers.\n\n'
            'Lifecycle transitions are owned by ``activity_lifecycle_service``; '
            'this module performs explicit row-level reads and writes only.\n'
            '"""\n\n' + text
        )
    path.write_text(text, encoding="utf-8", newline="\n")


def migrate_tests() -> None:
    for path in Path("tests").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        updated = text
        for old, new in ALIASES.items():
            updated = updated.replace(
                f"activity_service.{old}(",
                f"activity_service.{new}(",
            )
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")


def scan() -> None:
    offenders: list[str] = []
    for path in (Path("worktrace"), Path("tests")):
        for file_path in path.rglob("*.py"):
            source = file_path.read_text(encoding="utf-8")
            for old in REMOVE_FUNCTIONS:
                if f"activity_service.{old}(" in source:
                    offenders.append(f"{file_path}:activity_service.{old}")
    if offenders:
        raise RuntimeError("old activity write aliases remain: " + ", ".join(offenders))


def main() -> None:
    migrate_tests()
    remove_functions(Path("worktrace/services/activity_service.py"))
    scan()
    DIAGNOSTIC.unlink(missing_ok=True)
    WORKFLOW.unlink(missing_ok=True)
    SELF.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        failure = traceback.format_exc()
        subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)
        DIAGNOSTIC.parent.mkdir(exist_ok=True)
        DIAGNOSTIC.write_text(failure, encoding="utf-8")
        WORKFLOW.unlink(missing_ok=True)
