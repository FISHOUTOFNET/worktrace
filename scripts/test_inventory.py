#!/usr/bin/env python3
"""Static inventory for the WorkTrace pytest suite.

This script audits test structure; it does not replace pytest collection or
execution. Counts are static estimates based on test function definitions and
pytest marker syntax.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
__test__ = False

REQUIRED_MARKERS: dict[str, str] = {
    "unit": "Pure function or single-service tests without real threads, WebView GUI, or packaging flow.",
    "db": "Tests that use SQLite/temp_db or directly read/write the database.",
    "contract": "API, ViewModel, payload, boundary, or static contract tests.",
    "integration": "Cross service, API, bridge, or runtime integration tests.",
    "webview_static": "WebView static tests that directly read HTML/CSS/JS source.",
    "live_display": "Live clock, snapshot, ViewModel overlay, and frontend projection tests.",
    "collector_runtime": "Collector loop, pause/resume, idle, runtime startup gate, thread, or control channel tests.",
    "security_privacy": "Encryption, backup, privacy boundary, anonymization, or sensitive leak tests.",
    "packaging": "PyInstaller, installer, release docs, spec, or packaging smoke tests.",
    "slow": "High-runtime tests or tests that fit release/manual validation context.",
    "serial": "Future non-parallel tests. Marker only; parallel execution is not enabled.",
    "parallel_safe": "Future parallel candidates. Marker only; parallel execution is not enabled.",
}

BUILTIN_MARKS = {
    "filterwarnings",
    "parametrize",
    "skip",
    "skipif",
    "usefixtures",
    "xfail",
}

FEATURE_PATTERNS: dict[str, tuple[str, ...]] = {
    "temp_db": ("temp_db",),
    "get_connection": ("get_connection",),
    "monkeypatch.setattr": ("monkeypatch.setattr",),
    "threading": ("threading", "Thread("),
    "subprocess": ("subprocess",),
    "pyinstaller": ("pyinstaller", "PyInstaller"),
    "webview_static_helper": ("static_helpers", "read_all_js", "func_body", "html_section_by_id", "html_element_by_id", "js_catch_block"),
}

REVIEW_DB_PATTERNS = ("temp_db", "get_connection", "sqlite", "activity_log")
REVIEW_RUNTIME_PATTERNS = ("runtime", "collector", "thread", "pause", "resume", "idle")

_PLUS = r"\+"
_WS = r"\s*"
_DIGITS = r"\d+"
FIXED_WINDOW_RE = re.compile(
    r"(?<![\w])(source|body|section|snippet)"
    + _WS
    + r"\["
    + r"[^\]]*?"
    + r":"
    + r"[^\]]*?"
    + _PLUS
    + _WS
    + r"("
    + _DIGITS
    + r")"
    + r"[^\]]*?"
    + r"\]"
)


@dataclass
class InventoryFunction:
    name: str
    markers: set[str] = field(default_factory=set)


@dataclass
class FileInventory:
    path: str
    test_count: int = 0
    file_markers: set[str] = field(default_factory=set)
    tests: list[InventoryFunction] = field(default_factory=list)
    features: set[str] = field(default_factory=set)
    parse_error: str | None = None


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def repo_relative(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def discover_test_files(tests_dir: Path) -> list[Path]:
    if not tests_dir.exists() or not tests_dir.is_dir():
        raise FileNotFoundError(f"tests directory not found: {tests_dir}")
    return sorted(p for p in tests_dir.rglob("test_*.py") if p.is_file())


def _mark_name(node: ast.AST) -> str | None:
    """Return marker name from pytest.mark.foo expressions/calls."""
    target = node.func if isinstance(node, ast.Call) else node
    if not isinstance(target, ast.Attribute):
        return None
    value = target.value
    if (
        isinstance(value, ast.Attribute)
        and value.attr == "mark"
        and isinstance(value.value, ast.Name)
        and value.value.id == "pytest"
    ):
        return target.attr
    return None


def _marker_names_from_expr(node: ast.AST) -> set[str]:
    name = _mark_name(node)
    if name:
        return {name}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        names: set[str] = set()
        for elt in node.elts:
            names.update(_marker_names_from_expr(elt))
        return names
    return set()


def _decorator_markers(node: ast.AST) -> set[str]:
    decorators = getattr(node, "decorator_list", [])
    return {
        name
        for dec in decorators
        for name in _marker_names_from_expr(dec)
        if name not in BUILTIN_MARKS
    }


def _module_markers(tree: ast.Module) -> set[str]:
    markers: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
            continue
        markers.update(
            name
            for name in _marker_names_from_expr(node.value)
            if name not in BUILTIN_MARKS
        )
    return markers


def _collect_tests(tree: ast.Module, module_markers: set[str]) -> list[InventoryFunction]:
    tests: list[InventoryFunction] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            tests.append(
                InventoryFunction(
                    name=node.name,
                    markers=set(module_markers) | _decorator_markers(node),
                )
            )
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_markers = _decorator_markers(node)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                    tests.append(
                        InventoryFunction(
                            name=f"{node.name}.{child.name}",
                            markers=set(module_markers)
                            | class_markers
                            | _decorator_markers(child),
                        )
                    )
    return tests


def _scan_features(source: str) -> set[str]:
    found: set[str] = set()
    for feature, patterns in FEATURE_PATTERNS.items():
        if any(pattern in source for pattern in patterns):
            found.add(feature)
    return found


def parse_test_file(path: Path, repo_root: Path) -> FileInventory:
    rel = repo_relative(path, repo_root)
    source = path.read_text(encoding="utf-8")
    info = FileInventory(path=rel, features=_scan_features(source))
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        info.parse_error = f"{exc.msg} at line {exc.lineno}"
        return info
    module_markers = _module_markers(tree)
    tests = _collect_tests(tree, module_markers)
    info.tests = tests
    info.test_count = len(tests)
    info.file_markers = set(module_markers)
    for test in tests:
        info.file_markers.update(test.markers)
    return info


def registered_markers(pytest_config: Path) -> dict[str, str]:
    if not pytest_config.exists():
        return {}
    parser = configparser.ConfigParser()
    parser.read(pytest_config, encoding="utf-8")
    if not parser.has_section("pytest") or not parser.has_option("pytest", "markers"):
        return {}
    markers: dict[str, str] = {}
    for raw in parser.get("pytest", "markers").splitlines():
        line = raw.strip()
        if not line:
            continue
        name, _, desc = line.partition(":")
        markers[name.strip()] = desc.strip()
    return markers


def build_inventory(repo_root: Path = REPO_ROOT, tests_dir: Path | None = None) -> dict:
    repo_root = repo_root.resolve()
    tests_dir = tests_dir or repo_root / "tests"
    files = [parse_test_file(path, repo_root) for path in discover_test_files(tests_dir)]
    marker_names = sorted(REQUIRED_MARKERS)
    marker_stats = {
        name: {
            "files": sum(1 for f in files if name in f.file_markers),
            "tests": sum(1 for f in files for t in f.tests if name in t.markers),
        }
        for name in marker_names
    }
    unmarked_files = [f.path for f in files if not f.file_markers]
    unmarked_tests = [
        f"{f.path}::{t.name}"
        for f in files
        for t in f.tests
        if not t.markers
    ]
    feature_files = {
        feature: [f.path for f in files if feature in f.features]
        for feature in FEATURE_PATTERNS
    }
    manual_review = [
        f.path
        for f in files
        if any(pattern in f.path.lower() or pattern in (f.parse_error or "").lower() for pattern in ())
    ]
    manual_review = []
    for f in files:
        source = (repo_root / f.path).read_text(encoding="utf-8").lower()
        has_db = any(pattern in source for pattern in REVIEW_DB_PATTERNS)
        has_monkeypatch = "monkeypatch.setattr" in source
        has_runtime = any(pattern in source for pattern in REVIEW_RUNTIME_PATTERNS)
        if has_db and has_monkeypatch and has_runtime:
            manual_review.append(f.path)
    parse_errors = {f.path: f.parse_error for f in files if f.parse_error}
    return {
        "test_files": len(files),
        "estimated_tests": sum(f.test_count for f in files),
        "markers": marker_stats,
        "unmarked_files": {
            "count": len(unmarked_files),
            "files": unmarked_files,
        },
        "unmarked_tests": {
            "count": len(unmarked_tests),
            "tests": unmarked_tests,
        },
        "features": {
            feature: {
                "count": len(paths),
                "files": paths,
            }
            for feature, paths in feature_files.items()
        },
        "manual_review": {
            "count": len(manual_review),
            "files": manual_review,
        },
        "parse_errors": parse_errors,
    }


def _used_markers(repo_root: Path, tests_dir: Path) -> set[str]:
    used: set[str] = set()
    for path in discover_test_files(tests_dir):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=repo_relative(path, repo_root))
        except SyntaxError:
            continue
        used.update(_module_markers(tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                used.update(_decorator_markers(node))
    return used


def _load_runner(repo_root: Path):
    runner_path = repo_root / "scripts" / "run_affected_tests.py"
    if not runner_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("_worktrace_run_affected_tests", runner_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _runner_stale_targets(repo_root: Path) -> list[str]:
    runner = _load_runner(repo_root)
    if runner is None:
        return []
    stale: list[str] = []
    for rule in getattr(runner, "RULES", []):
        for target in rule.get("tests", []):
            clean = target.replace("\\", "/").rstrip("/")
            if clean and not (repo_root / clean).exists():
                stale.append(f"{rule['id']}: {target}")
    return stale


def run_checks(repo_root: Path = REPO_ROOT, tests_dir: Path | None = None) -> CheckResult:
    repo_root = repo_root.resolve()
    tests_dir = tests_dir or repo_root / "tests"
    result = CheckResult()
    try:
        inventory = build_inventory(repo_root, tests_dir)
    except Exception as exc:
        result.errors.append(f"inventory could not parse tests directory: {exc}")
        return result

    registered = registered_markers(repo_root / "pytest.ini")
    for marker in REQUIRED_MARKERS:
        if marker not in registered:
            result.errors.append(f"pytest marker not registered: {marker}")

    used = _used_markers(repo_root, tests_dir)
    for marker in sorted(used - set(registered) - BUILTIN_MARKS):
        result.errors.append(f"test uses unregistered pytest marker: {marker}")

    webview_conftest = tests_dir / "webview" / "conftest.py"
    if webview_conftest.exists():
        result.errors.append("tests/webview/conftest.py must not exist")

    webview_dir = tests_dir / "webview"
    if webview_dir.exists():
        for path in sorted(webview_dir.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(source.splitlines(), 1):
                for match in FIXED_WINDOW_RE.finditer(line):
                    if match.group(2) != "1":
                        rel = repo_relative(path, repo_root)
                        result.errors.append(
                            f"{rel}:{line_no}: fixed window slicing is forbidden"
                        )

    for rel, error in inventory["parse_errors"].items():
        result.errors.append(f"{rel}: {error}")

    if inventory["unmarked_tests"]["count"]:
        result.warnings.append(
            f"{inventory['unmarked_tests']['count']} estimated tests are unmarked; "
            "marker coverage is intentionally incremental in this phase."
        )

    for stale in _runner_stale_targets(repo_root):
        result.warnings.append(f"stale affected-runner target mapping: {stale}")

    return result


def render_text(inventory: dict) -> str:
    lines = [
        "WorkTrace Test Inventory",
        f"Test files: {inventory['test_files']}",
        f"Estimated tests: {inventory['estimated_tests']}",
        "",
        "Markers:",
    ]
    for name, stats in inventory["markers"].items():
        lines.append(f"  {name}: {stats['files']} files, {stats['tests']} tests")
    lines.extend(
        [
            "",
            f"Unmarked files: {inventory['unmarked_files']['count']}",
            f"Unmarked tests: {inventory['unmarked_tests']['count']}",
            "",
            "Feature signals:",
        ]
    )
    for name, data in inventory["features"].items():
        lines.append(f"  {name}: {data['count']} files")
    lines.extend(
        [
            "",
            f"Manual review candidates: {inventory['manual_review']['count']}",
        ]
    )
    for rel in inventory["manual_review"]["files"]:
        lines.append(f"  - {rel}")
    return "\n".join(lines)


def render_markdown(inventory: dict) -> str:
    lines = [
        "# WorkTrace Test Inventory",
        "",
        f"- Test files: {inventory['test_files']}",
        f"- Estimated tests: {inventory['estimated_tests']}",
        f"- Unmarked files: {inventory['unmarked_files']['count']}",
        f"- Unmarked tests: {inventory['unmarked_tests']['count']}",
        "",
        "## Markers",
        "",
        "| Marker | Files | Estimated tests |",
        "| --- | ---: | ---: |",
    ]
    for name, stats in inventory["markers"].items():
        lines.append(f"| `{name}` | {stats['files']} | {stats['tests']} |")
    lines.extend(
        [
            "",
            "## Feature Signals",
            "",
            "| Signal | Files |",
            "| --- | ---: |",
        ]
    )
    for name, data in inventory["features"].items():
        lines.append(f"| `{name}` | {data['count']} |")
    lines.extend(["", "## Manual Review Candidates", ""])
    if inventory["manual_review"]["files"]:
        lines.extend(f"- `{rel}`" for rel in inventory["manual_review"]["files"])
    else:
        lines.append("- None")
    return "\n".join(lines)


def _print_check(result: CheckResult) -> None:
    if result.errors:
        print("Inventory check errors:")
        for error in result.errors:
            print(f"  - {error}")
    else:
        print("Inventory check errors: none")
    if result.warnings:
        print("Inventory check warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit WorkTrace pytest inventory.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="Emit inventory as JSON.")
    group.add_argument("--markdown", action="store_true", help="Emit inventory as Markdown.")
    group.add_argument("--check", action="store_true", help="Run governance consistency checks.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    if args.check:
        result = run_checks(args.repo_root)
        _print_check(result)
        return 1 if result.errors else 0

    inventory = build_inventory(args.repo_root)
    if args.json:
        print(json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.markdown:
        print(render_markdown(inventory))
    else:
        print(render_text(inventory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
