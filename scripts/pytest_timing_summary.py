#!/usr/bin/env python3
"""Generate a structured timing summary from pytest JUnit XML and log output.

Runs after a successful CI pytest step to produce a JSON artifact with test
counts, total elapsed time, slowest tests, slowest files, and (where
available from ``--durations`` output) setup/call/teardown totals. The
summary is uploaded as a 1-day-retention artifact for trend observation.

Failure to generate the summary must not mask the underlying test result:
the script prints a clear status line and returns 0 even when inputs are
missing or malformed. The workflow step uses ``continue-on-error: true``
so a summary failure never fails a green run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_TOP_TESTS = 50
_TOP_FILES = 20

_DURATION_LINE = re.compile(
    r"^\s*(?P<seconds>\d+(?:\.\d+)?)\s*s\s+"
    r"(?P<phase>setup|call|teardown)\s+(?P<nodeid>.+?)\s*$"
)


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _find_testsuite(root: ET.Element) -> ET.Element | None:
    if _local_name(root.tag) == "testsuite":
        return root
    for child in root.iter():
        if _local_name(child.tag) == "testsuite":
            return child
    return None


def _parse_junit(junit_path: Path) -> tuple[int, float, list[dict[str, Any]]]:
    """Parse JUnit XML, returning (test_count, total_seconds, testcases)."""
    if not junit_path.exists():
        return 0, 0.0, []
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError:
        return 0, 0.0, []
    root = tree.getroot()
    suite = _find_testsuite(root)
    if suite is None:
        return 0, 0.0, []

    test_count = _safe_int(suite.attrib.get("tests"))
    total_seconds = _safe_float(suite.attrib.get("time"))

    testcases: list[dict[str, Any]] = []
    for tc in suite.iter():
        if _local_name(tc.tag) != "testcase":
            continue
        classname = tc.attrib.get("classname", "").strip()
        name = tc.attrib.get("name", "").strip()
        time_seconds = _safe_float(tc.attrib.get("time"))
        skipped = any(_local_name(child.tag) == "skipped" for child in tc)
        failed = any(_local_name(child.tag) in {"failure", "error"} for child in tc)
        testcases.append(
            {
                "test_id": f"{classname}::{name}" if classname else name,
                "classname": classname,
                "name": name,
                "time_seconds": time_seconds,
                "skipped": skipped,
                "failed": failed,
            }
        )
    return test_count, total_seconds, testcases


def _parse_durations(log_path: Path) -> tuple[float | None, float | None, float | None]:
    """Parse pytest ``--durations`` output for setup/call/teardown totals.

    Returns ``(setup_seconds, call_seconds, teardown_seconds)``. Each value
    is the sum of the corresponding segment across all reported entries, or
    ``None`` if no durations section was found.
    """
    if not log_path.exists():
        return None, None, None
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, None

    setup_total = 0.0
    call_total = 0.0
    teardown_total = 0.0
    found_any = False
    for line in text.splitlines():
        match = _DURATION_LINE.match(line)
        if not match:
            continue
        found_any = True
        phase = match.group("phase")
        seconds = float(match.group("seconds"))
        if phase == "setup":
            setup_total += seconds
        elif phase == "call":
            call_total += seconds
        elif phase == "teardown":
            teardown_total += seconds
    if not found_any:
        return None, None, None
    return setup_total, call_total, teardown_total


def _top_tests(testcases: list[dict[str, Any]], top_n: int = _TOP_TESTS) -> list[dict[str, Any]]:
    sorted_tests = sorted(testcases, key=lambda x: x["time_seconds"], reverse=True)
    return [
        {
            "test_id": tc["test_id"],
            "time_seconds": round(tc["time_seconds"], 4),
        }
        for tc in sorted_tests[:top_n]
    ]


def _aggregate_files(testcases: list[dict[str, Any]], top_n: int = _TOP_FILES) -> list[dict[str, Any]]:
    """Aggregate testcase times by file (derived from classname root)."""
    file_totals: dict[str, float] = {}
    for tc in testcases:
        parts = tc["classname"].split(".")
        if len(parts) >= 2:
            file_key = ".".join(parts[:2])
        else:
            file_key = tc["classname"] or "(unknown)"
        file_totals[file_key] = file_totals.get(file_key, 0.0) + tc["time_seconds"]
    sorted_files = sorted(file_totals.items(), key=lambda x: x[1], reverse=True)
    return [{"file": k, "time_seconds": round(v, 4)} for k, v in sorted_files[:top_n]]


def _marker_totals_placeholder() -> dict[str, Any]:
    """Marker totals are not available from JUnit XML.

    Populating this would require a separate collection-only run or a custom
    pytest plugin to record markers during execution. Left as an empty dict
    for schema stability; future work can populate it without breaking
    consumers.
    """
    return {}


def build_summary(
    *,
    junit_path: Path,
    log_path: Path,
    revision: str,
    runner: str,
    python_version: str,
    suite: str = "",
) -> dict[str, Any]:
    test_count, total_seconds, testcases = _parse_junit(junit_path)
    setup_seconds, call_seconds, teardown_seconds = _parse_durations(log_path)
    return {
        "schema_version": _SCHEMA_VERSION,
        "revision": revision,
        "runner": runner,
        "python_version": python_version,
        "suite": suite,
        "test_count": test_count,
        "pytest_elapsed_seconds": round(total_seconds, 4),
        "top_tests": _top_tests(testcases),
        "top_files": _aggregate_files(testcases),
        "marker_totals": _marker_totals_placeholder(),
        "setup_seconds": round(setup_seconds, 4) if setup_seconds is not None else None,
        "call_seconds": round(call_seconds, 4) if call_seconds is not None else None,
        "teardown_seconds": round(teardown_seconds, 4) if teardown_seconds is not None else None,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", default="")
    parser.add_argument("--runner", default="")
    parser.add_argument("--python-version", default="")
    parser.add_argument(
        "--suite",
        default="",
        help="Suite label (e.g. 'standard', 'benchmark') for trend grouping.",
    )
    return parser.parse_args()


def main() -> int:
    _configure_utf8()
    args = _parse_args()

    try:
        summary = build_summary(
            junit_path=args.junit,
            log_path=args.log,
            revision=args.revision,
            runner=args.runner,
            python_version=args.python_version,
            suite=args.suite,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"timing_summary_status=ready "
            f"suite={summary['suite'] or 'standard'} "
            f"test_count={summary['test_count']} "
            f"elapsed={summary['pytest_elapsed_seconds']:.2f}s"
        )
        # Best-effort GitHub step summary append. Never fail on summary write.
        step_summary = args.output.parent / "pytest-timing-summary.md"
        try:
            md_lines = [
                "## pytest timing summary",
                f"- revision: `{summary['revision']}`",
                f"- runner: {summary['runner']}",
                f"- python: {summary['python_version']}",
                f"- suite: {summary['suite'] or 'standard'}",
                f"- test_count: {summary['test_count']}",
                f"- pytest_elapsed_seconds: {summary['pytest_elapsed_seconds']}",
                f"- setup_seconds: {summary['setup_seconds']}",
                f"- call_seconds: {summary['call_seconds']}",
                f"- teardown_seconds: {summary['teardown_seconds']}",
                "",
                "### top 10 slowest tests",
                "| seconds | test |",
                "|---|---|",
            ]
            for tc in summary["top_tests"][:10]:
                md_lines.append(f"| {tc['time_seconds']} | `{tc['test_id']}` |")
            step_summary.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
            if summary_github_output := os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(summary_github_output, "a", encoding="utf-8") as handle:
                    handle.write("\n".join(md_lines) + "\n")
        except OSError:
            pass
    except Exception as exc:  # noqa: BLE001 - summary failure must never mask tests
        print(f"timing_summary_status=fallback reason={type(exc).__name__}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
