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
TEST_POLICY_PATH = REPO_ROOT / "test_policy.json"
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
    line_count: int = 0
    file_markers: set[str] = field(default_factory=set)
    tests: list[InventoryFunction] = field(default_factory=list)
    features: set[str] = field(default_factory=set)
    risk_signals: set[str] = field(default_factory=set)
    owners: set[str] = field(default_factory=set)
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


def load_test_policy(repo_root: Path = REPO_ROOT) -> dict:
    policy_path = repo_root / "test_policy.json"
    if not policy_path.exists():
        return {
            "risk_signals": {},
            "risk_marker_overrides": [],
            "budgets": {
                "max_lines_per_test_file": 1200,
                "max_test_functions_per_test_file": 120,
                "overrides": [],
            },
            "owners": [],
        }
    return json.loads(policy_path.read_text(encoding="utf-8"))


def _path_matches(path: str, pattern: str) -> bool:
    clean_path = path.replace("\\", "/")
    clean_pattern = pattern.replace("\\", "/")
    return clean_path == clean_pattern or clean_path.startswith(clean_pattern)


def _has_override(policy: dict, path: str, *, signal: str | None = None) -> bool:
    for override in policy.get("risk_marker_overrides", []):
        override_signal = override.get("signal")
        if signal is not None and override_signal != signal:
            continue
        if not str(override.get("reason", "")).strip():
            continue
        if _path_matches(path, str(override.get("path", ""))):
            return True
    return False


def _budget_override_reason(policy: dict, path: str) -> str | None:
    for override in policy.get("budgets", {}).get("overrides", []):
        if _path_matches(path, str(override.get("path", ""))):
            reason = str(override.get("reason", "")).strip()
            return reason or None
    return None


def _owners_for_path(policy: dict, path: str) -> set[str]:
    owners: set[str] = set()
    for owner in policy.get("owners", []):
        if any(_path_matches(path, str(pattern)) for pattern in owner.get("paths", [])):
            owners.add(str(owner.get("name", "")).strip())
    return {owner for owner in owners if owner}


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


def _scan_risk_signals(source: str, policy: dict) -> set[str]:
    found: set[str] = set()
    for signal, config in policy.get("risk_signals", {}).items():
        patterns = tuple(config.get("patterns", ()))
        if any(pattern in source for pattern in patterns):
            found.add(signal)
    return found


def parse_test_file(path: Path, repo_root: Path, policy: dict | None = None) -> FileInventory:
    rel = repo_relative(path, repo_root)
    source = path.read_text(encoding="utf-8")
    policy = policy or load_test_policy(repo_root)
    info = FileInventory(
        path=rel,
        line_count=len(source.splitlines()),
        features=_scan_features(source),
        risk_signals=_scan_risk_signals(source, policy),
        owners=_owners_for_path(policy, rel),
    )
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
    policy = load_test_policy(repo_root)
    files = [parse_test_file(path, repo_root, policy) for path in discover_test_files(tests_dir)]
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
    risk_signal_files = {
        signal: [f.path for f in files if signal in f.risk_signals]
        for signal in policy.get("risk_signals", {})
    }
    budget_config = policy.get("budgets", {})
    max_lines = int(budget_config.get("max_lines_per_test_file", 1200))
    max_tests = int(budget_config.get("max_test_functions_per_test_file", 120))
    over_budget = []
    for f in files:
        if f.line_count <= max_lines and f.test_count <= max_tests:
            continue
        over_budget.append(
            {
                "path": f.path,
                "lines": f.line_count,
                "tests": f.test_count,
                "max_lines": max_lines,
                "max_tests": max_tests,
                "override_reason": _budget_override_reason(policy, f.path),
            }
        )
    missing_owner = [f.path for f in files if not f.owners]
    real_sleep_files = risk_signal_files.get("sleep", [])
    marker_mismatches = []
    for f in files:
        for signal in sorted(f.risk_signals):
            required = set(
                policy.get("risk_signals", {})
                .get(signal, {})
                .get("required_any_markers", [])
            )
            if not required or f.file_markers & required:
                continue
            marker_mismatches.append(
                {
                    "path": f.path,
                    "signal": signal,
                    "required_any_markers": sorted(required),
                    "markers": sorted(f.file_markers),
                    "override": _has_override(policy, f.path, signal=signal),
                }
            )
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
        "risk_signals": {
            signal: {
                "count": len(paths),
                "files": paths,
            }
            for signal, paths in risk_signal_files.items()
        },
        "budgets": {
            "max_lines_per_test_file": max_lines,
            "max_test_functions_per_test_file": max_tests,
            "over_budget": over_budget,
        },
        "owner_contracts": {
            "missing_count": len(missing_owner),
            "missing_files": missing_owner,
            "owners": {
                owner.get("name"): [
                    f.path for f in files if str(owner.get("name")) in f.owners
                ]
                for owner in policy.get("owners", [])
            },
        },
        "real_sleep_files": {
            "count": len(real_sleep_files),
            "files": real_sleep_files,
        },
        "marker_mismatches": {
            "count": len(marker_mismatches),
            "files": marker_mismatches,
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

    policy = load_test_policy(repo_root)
    for rel in inventory["real_sleep_files"]["files"]:
        if not _has_override(policy, rel, signal="sleep"):
            result.errors.append(f"{rel}: explicit sleep risk signal is forbidden")

    for mismatch in inventory["marker_mismatches"]["files"]:
        if mismatch["override"]:
            continue
        result.errors.append(
            "{path}: risk signal `{signal}` requires one of markers {markers}".format(
                path=mismatch["path"],
                signal=mismatch["signal"],
                markers=", ".join(mismatch["required_any_markers"]),
            )
        )

    for budget in inventory["budgets"]["over_budget"]:
        if budget["override_reason"]:
            continue
        result.errors.append(
            "{path}: test file exceeds budget ({lines} lines/{tests} tests; "
            "limits {max_lines} lines/{max_tests} tests) and needs a reason override".format(
                **budget
            )
        )

    for stale in _runner_stale_targets(repo_root):
        result.errors.append(f"stale affected-runner target mapping: {stale}")

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
    lines.extend(["", "Slow-test risk signals:"])
    for name, data in inventory["risk_signals"].items():
        lines.append(f"  {name}: {data['count']} files")
    lines.extend(
        [
            "",
            "Over-budget files:",
        ]
    )
    if inventory["budgets"]["over_budget"]:
        for item in inventory["budgets"]["over_budget"]:
            suffix = "with override" if item["override_reason"] else "no override"
            lines.append(
                f"  - {item['path']}: {item['lines']} lines, "
                f"{item['tests']} tests ({suffix})"
            )
    else:
        lines.append("  None")
    lines.extend(
        [
            "",
            f"Missing owner/contract files: {inventory['owner_contracts']['missing_count']}",
            f"Real sleep risk files: {inventory['real_sleep_files']['count']}",
            f"Marker/risk mismatches: {inventory['marker_mismatches']['count']}",
        ]
    )
    for mismatch in inventory["marker_mismatches"]["files"]:
        status = "override" if mismatch["override"] else "missing marker"
        lines.append(
            f"  - {mismatch['path']}: {mismatch['signal']} -> "
            f"{'/'.join(mismatch['required_any_markers'])} ({status})"
        )
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
    lines.extend(
        [
            "",
            "## Slow-Test Risk Signals",
            "",
            "| Signal | Files |",
            "| --- | ---: |",
        ]
    )
    for name, data in inventory["risk_signals"].items():
        lines.append(f"| `{name}` | {data['count']} |")
    lines.extend(["", "## Over-Budget Files", ""])
    if inventory["budgets"]["over_budget"]:
        for item in inventory["budgets"]["over_budget"]:
            status = "override" if item["override_reason"] else "no override"
            lines.append(
                f"- `{item['path']}`: {item['lines']} lines, "
                f"{item['tests']} tests ({status})"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Marker / Risk Mismatches", ""])
    if inventory["marker_mismatches"]["files"]:
        for item in inventory["marker_mismatches"]["files"]:
            status = "override" if item["override"] else "missing marker"
            lines.append(
                f"- `{item['path']}`: `{item['signal']}` requires "
                f"`{'` or `'.join(item['required_any_markers'])}` ({status})"
            )
    else:
        lines.append("- None")
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
