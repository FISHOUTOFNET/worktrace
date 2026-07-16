from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "diagnostics" / "runtime-settings-call-inventory.txt"

RUNTIME_KEYS = frozenset(
    {
        "current_activity_snapshot",
        "pending_short_seconds",
        "pending_short_carry_provenance",
    }
)
SETTINGS_FUNCTIONS = frozenset(
    {
        "get_setting",
        "set_setting",
        "get_bool_setting",
        "get_int_setting",
    }
)
RUNTIME_COMPAT_FUNCTIONS = frozenset(
    {
        "read_runtime_activity_snapshot_raw",
        "restore_runtime_activity_snapshot",
        "get_legacy_runtime_setting",
        "set_legacy_runtime_setting",
    }
)
SETTINGS_API_COMPAT_FUNCTIONS = frozenset(
    {
        "get_setting_value",
        "set_setting_value",
        "get_bool_setting_value",
        "get_int_setting_value",
        "get_list_setting_value",
        "set_list_setting_value",
    }
)


def _imports(tree: ast.AST):
    direct: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "worktrace.services.settings_service":
                for item in node.names:
                    direct[item.asname or item.name] = ("settings", item.name)
            elif module == "worktrace.services.runtime_activity_state_service":
                for item in node.names:
                    direct[item.asname or item.name] = ("runtime", item.name)
            elif module == "worktrace.api.settings_api":
                for item in node.names:
                    direct[item.asname or item.name] = ("settings_api", item.name)
            elif module == "worktrace.services":
                for item in node.names:
                    if item.name == "settings_service":
                        modules[item.asname or item.name] = "settings"
                    elif item.name == "runtime_activity_state_service":
                        modules[item.asname or item.name] = "runtime"
            elif module == "worktrace.api":
                for item in node.names:
                    if item.name == "settings_api":
                        modules[item.asname or item.name] = "settings_api"
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "worktrace.services.settings_service":
                    modules[item.asname or "settings_service"] = "settings"
                elif item.name == "worktrace.services.runtime_activity_state_service":
                    modules[item.asname or "runtime_activity_state_service"] = "runtime"
                elif item.name == "worktrace.api.settings_api":
                    modules[item.asname or "settings_api"] = "settings_api"
    return direct, modules


def _resolved_call(node: ast.Call, direct, modules):
    func = node.func
    if isinstance(func, ast.Name):
        return direct.get(func.id)
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in modules
    ):
        return modules[func.value.id], func.attr
    return None


def calls(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    direct, modules = _imports(tree)
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        resolved = _resolved_call(node, direct, modules)
        if resolved is None:
            continue
        owner, name = resolved
        if owner == "settings" and name in SETTINGS_FUNCTIONS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value in RUNTIME_KEYS:
                found.add((node.lineno, f"settings.{name}({first.value})"))
        elif owner == "runtime" and name in RUNTIME_COMPAT_FUNCTIONS:
            found.add((node.lineno, f"runtime.{name}"))
        elif owner == "settings_api" and name in SETTINGS_API_COMPAT_FUNCTIONS:
            found.add((node.lineno, f"settings_api.{name}"))
    return sorted(found)


def main() -> int:
    rows: list[str] = []
    for root_name in ("worktrace", "tests"):
        for path in sorted((ROOT / root_name).rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            for line, value in calls(path):
                rows.append(f"{relative}:{line}: {value}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "runtime/settings precise call inventory\n"
        f"call_count={len(rows)}\n\n"
        + ("\n".join(rows) if rows else "no calls")
        + "\n",
        encoding="utf-8",
    )
    print(OUTPUT.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
