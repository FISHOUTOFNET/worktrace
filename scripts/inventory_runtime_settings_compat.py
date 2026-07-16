from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "diagnostics" / "runtime-settings-compat-inventory.txt"

SYMBOLS = frozenset(
    {
        "CURRENT_ACTIVITY_SNAPSHOT_KEY",
        "PENDING_SHORT_SECONDS_KEY",
        "PENDING_CARRY_PROVENANCE_KEY",
        "read_runtime_activity_snapshot_raw",
        "restore_runtime_activity_snapshot",
        "get_legacy_runtime_setting",
        "set_legacy_runtime_setting",
        "get_setting_value",
        "set_setting_value",
        "get_bool_setting_value",
        "get_int_setting_value",
        "get_list_setting_value",
        "set_list_setting_value",
    }
)
RUNTIME_KEY_LITERALS = frozenset(
    {
        "current_activity_snapshot",
        "pending_short_seconds",
        "pending_short_carry_provenance",
    }
)


def references(path: Path) -> list[tuple[int, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[int, str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in SYMBOLS:
            found.add((node.lineno, "symbol", node.id))
        elif isinstance(node, ast.Attribute) and node.attr in SYMBOLS:
            found.add((node.lineno, "attribute", node.attr))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in RUNTIME_KEY_LITERALS
        ):
            found.add((node.lineno, "runtime_key", node.value))
    return sorted(found)


def main() -> int:
    rows: list[str] = []
    for root_name in ("worktrace", "tests"):
        for path in sorted((ROOT / root_name).rglob("*.py")):
            if path == Path(__file__).resolve():
                continue
            relative = path.relative_to(ROOT).as_posix()
            for line, kind, value in references(path):
                rows.append(f"{relative}:{line}: {kind}: {value}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "runtime/settings compatibility inventory\n"
        f"reference_count={len(rows)}\n\n"
        + ("\n".join(rows) if rows else "no references")
        + "\n",
        encoding="utf-8",
    )
    print(OUTPUT.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
