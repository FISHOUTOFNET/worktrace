#!/usr/bin/env python3
"""Generate a structured timing summary from pytest JUnit XML and log output.

Produces a JSON artifact with test counts, total elapsed time, slowest tests,
slowest files, and (where available from ``--durations`` output) setup/call/
teardown totals.

Exit codes are honest and machine-readable so workflows can decide whether to
gate on summary generation via ``continue-on-error`` rather than relying on the
tool to mask failures::

    0 = summary generated successfully
    2 = input file missing (junit or log path does not exist)
    3 = JUnit XML parse failure or incomplete (no testsuite element)
    4 = summary output write failure
    5 = data semantic validation failure (e.g. negative counts)

The tool must never silently return 0 when it could not produce a valid
summary.  Workflow-level gating is the responsibility of the caller.
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

_SCHEMA_VERSION = 2
_TOP_TESTS = 50
_TOP_FILES = 20

# Exit codes — documented in the module docstring.
EXIT_OK = 0
EXIT_INPUT_MISSING = 2
EXIT_JUNIT_PARSE = 3
EXIT_OUTPUT = 4
EXIT_SEMANTIC = 5

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


def _parse_junit(junit_path: Path) -> tuple[int, int, int, int, float, list[dict[str, Any]]]:
    """Parse JUnit XML.

    Returns ``(test_count, failure_count, error_count, skipped_count,
    total_seconds, testcases)``.  Raises ``ET.ParseError`` on malformed XML
    and ``ValueError`` when no ``testsuite`` element is present.
    """
    tree = ET.parse(junit_path)
    root = tree.getroot()
    suite = _find_testsuite(root)
    if suite is None:
        raise ValueError("no testsuite element found in JUnit XML")

    test_count = _safe_int(suite.attrib.get("tests"))
    failure_count = _safe_int(suite.attrib.get("failures"))
    error_count = _safe_int(suite.attrib.get("errors"))
    skipped_count = _safe_int(suite.attrib.get("skipped"))
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
    return test_count, failure_count, error_count, skipped_count, total_seconds, testcases


def _parse_durations(log_path: Path) -> tuple[float | None, float | None, float | None]:
    """Parse pytest ``--durations`` output for setup/call/teardown totals.

    Returns ``(setup_seconds, call_seconds, teardown_seconds)``. Each value
    is the sum of the corresponding segment across all reported entries, or
    ``None`` if no durations section was found.
    """
    text = log_path.read_text(encoding="utf-8", errors="replace")

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


def _runner_metadata() -> dict[str, str | None]:
    """Collect runner metadata from GitHub Actions environment variables.

    Returns a dict with runner_os, runner_arch, runner_image, runner_image_version.
    Values are ``None`` when not running on GitHub Actions or when the env var
    is absent — the summary records the honest state rather than fabricating
    a value.
    """
    on_github = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    if not on_github:
        return {
            "runner_os": None,
            "runner_arch": None,
            "runner_image": None,
            "runner_image_version": None,
        }
    return {
        "runner_os": os.environ.get("RUNNER_OS") or None,
        "runner_arch": os.environ.get("RUNNER_ARCH") or None,
        "runner_image": os.environ.get("ImageOS") or None,
        "runner_image_version": os.environ.get("ImageVersion") or None,
    }


def build_summary(
    *,
    junit_path: Path,
    log_path: Path,
    revision: str,
    runner: str,
    python_version: str,
    suite: str = "",
    commit_sha: str = "",
) -> dict[str, Any]:
    """Build the timing summary dict.

    Raises ``ValueError`` for semantic problems (missing testsuite, negative
    counts).  Callers map exceptions to the appropriate non-zero exit code.
    """
    junit_exists = junit_path.exists()
    log_exists = log_path.exists()

    if not junit_exists:
        raise FileNotFoundError(f"JUnit file not found: {junit_path}")
    if not log_exists:
        raise FileNotFoundError(f"Log file not found: {log_path}")

    test_count, failure_count, error_count, skipped_count, total_seconds, testcases = _parse_junit(junit_path)
    setup_seconds, call_seconds, teardown_seconds = _parse_durations(log_path)

    # Semantic validation: counts must not be negative.
    if test_count < 0 or failure_count < 0 or error_count < 0 or skipped_count < 0:
        raise ValueError(
            f"negative count in JUnit: tests={test_count} "
            f"failures={failure_count} errors={error_count} skipped={skipped_count}"
        )

    runner_info = _runner_metadata()

    return {
        "schema_version": _SCHEMA_VERSION,
        "generation_status": "ok",
        "revision": revision,
        "commit_sha": commit_sha or None,
        "suite": suite,
        "runner": runner,
        "runner_os": runner_info["runner_os"],
        "runner_arch": runner_info["runner_arch"],
        "runner_image": runner_info["runner_image"],
        "runner_image_version": runner_info["runner_image_version"],
        "python_version": python_version,
        "test_count": test_count,
        "failure_count": failure_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "pytest_elapsed_seconds": round(total_seconds, 4),
        "top_tests": _top_tests(testcases),
        "top_files": _aggregate_files(testcases),
        "setup_seconds": round(setup_seconds, 4) if setup_seconds is not None else None,
        "call_seconds": round(call_seconds, 4) if call_seconds is not None else None,
        "teardown_seconds": round(teardown_seconds, 4) if teardown_seconds is not None else None,
        "source_junit_exists": True,
        "source_log_exists": True,
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
    parser.add_argument(
        "--commit-sha",
        default="",
        help="Commit SHA. Defaults to GITHUB_SHA environment variable if set.",
    )
    return parser.parse_args()


def _emit_status(status: str, **extra: Any) -> None:
    parts = [f"timing_summary_status={status}"]
    for key, value in extra.items():
        parts.append(f"{key}={value}")
    print(" ".join(parts), flush=True)


def main() -> int:
    _configure_utf8()
    args = _parse_args()

    commit_sha = args.commit_sha or os.environ.get("GITHUB_SHA", "")

    junit_exists = args.junit.exists()
    log_exists = args.log.exists()
    if not junit_exists or not log_exists:
        _emit_status(
            "input_missing",
            junit_exists=str(junit_exists).lower(),
            log_exists=str(log_exists).lower(),
        )
        return EXIT_INPUT_MISSING

    try:
        summary = build_summary(
            junit_path=args.junit,
            log_path=args.log,
            revision=args.revision,
            runner=args.runner,
            python_version=args.python_version,
            suite=args.suite,
            commit_sha=commit_sha,
        )
    except ET.ParseError as exc:
        _emit_status("junit_parse_error", reason=type(exc).__name__)
        return EXIT_JUNIT_PARSE
    except ValueError as exc:
        msg = str(exc)
        if "no testsuite" in msg:
            _emit_status("junit_parse_error", reason="no_testsuite")
            return EXIT_JUNIT_PARSE
        _emit_status("semantic_error", reason=type(exc).__name__)
        return EXIT_SEMANTIC

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        _emit_status("output_error", reason=type(exc).__name__)
        return EXIT_OUTPUT

    _emit_status(
        "ready",
        suite=summary["suite"] or "standard",
        test_count=summary["test_count"],
        elapsed=f"{summary['pytest_elapsed_seconds']:.2f}s",
    )

    # Best-effort GitHub step summary append. Never affects the exit code.
    try:
        step_summary = args.output.parent / "pytest-timing-summary.md"
        md_lines = [
            "## pytest timing summary",
            f"- revision: `{summary['revision']}`",
            f"- commit_sha: `{summary['commit_sha'] or 'unknown'}`",
            f"- runner: {summary['runner']}",
            f"- runner_os: {summary['runner_os']}",
            f"- runner_arch: {summary['runner_arch']}",
            f"- python: {summary['python_version']}",
            f"- suite: {summary['suite'] or 'standard'}",
            f"- test_count: {summary['test_count']}",
            f"- failures: {summary['failure_count']}",
            f"- errors: {summary['error_count']}",
            f"- skipped: {summary['skipped_count']}",
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

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
