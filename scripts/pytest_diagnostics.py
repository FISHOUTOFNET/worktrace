#!/usr/bin/env python3
"""Emit compact, stable diagnostics from a pytest JUnit report."""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MANIFEST_BEGIN = "=== PYTEST_FAILURE_MANIFEST_BEGIN ==="
MANIFEST_END = "=== PYTEST_FAILURE_MANIFEST_END ==="
DETAILS_BEGIN = "=== PYTEST_FAILURE_DETAILS_BEGIN ==="
DETAILS_END = "=== PYTEST_FAILURE_DETAILS_END ==="
FALLBACK_BEGIN = "=== PYTEST_LOG_FALLBACK_BEGIN ==="
FALLBACK_END = "=== PYTEST_LOG_FALLBACK_END ==="


@dataclass(frozen=True)
class Problem:
    test_id: str
    kind: str
    location: str
    message: str
    details: str


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _single_line(value: str, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value or "").strip()
    if not compact:
        return "(no message)"
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _bounded_details(value: str, *, limit: int) -> str:
    normalized = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return "(no traceback details)"
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 18)].rstrip() + "\n... truncated ..."


def _source_location(text: str) -> str:
    patterns = (
        re.compile(r"(?P<path>(?:[A-Za-z]:)?[^\r\n:]*?\.py):(?P<line>\d+)(?::|$)"),
        re.compile(r'File "(?P<path>[^"]+\.py)", line (?P<line>\d+)'),
    )
    for line in (text or "").splitlines():
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                path = match.group("path").strip()
                return f"{path}:{match.group('line')}"
    return "(unknown)"


def _problem_child(testcase: ET.Element) -> ET.Element | None:
    for child in testcase:
        if _local_name(child.tag) in {"failure", "error"}:
            return child
    return None


def _test_id(testcase: ET.Element) -> str:
    class_name = testcase.attrib.get("classname", "").strip()
    test_name = testcase.attrib.get("name", "").strip() or "(unnamed test)"
    return f"{class_name}::{test_name}" if class_name else test_name


def _collect(root: ET.Element, *, detail_limit: int) -> tuple[int, int, list[Problem]]:
    testcases = [element for element in root.iter() if _local_name(element.tag) == "testcase"]
    skipped = 0
    problems: list[Problem] = []

    for testcase in testcases:
        if any(_local_name(child.tag) == "skipped" for child in testcase):
            skipped += 1
        problem = _problem_child(testcase)
        if problem is None:
            continue

        kind = _local_name(problem.tag)
        raw_details = problem.text or ""
        raw_message = problem.attrib.get("message", "") or raw_details
        problems.append(
            Problem(
                test_id=_test_id(testcase),
                kind=kind,
                location=_source_location(raw_details),
                message=_single_line(raw_message, limit=240),
                details=_bounded_details(raw_details or raw_message, limit=detail_limit),
            )
        )

    return len(testcases), skipped, problems


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("`", "\\`").replace("\n", " ")


def _append_summary(path: Path | None, lines: Iterable[str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for line in lines:
            stream.write(line)
            stream.write("\n")


def _append_github_outputs(problems: list[Problem]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    first_failure = problems[0].test_id if problems else ""
    first_location = problems[0].location if problems else ""
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"problem_count={len(problems)}\n")
        stream.write(f"first_failure={_single_line(first_failure, limit=160)}\n")
        stream.write(f"first_location={_single_line(first_location, limit=120)}\n")


def _emit_manifest(total: int, skipped: int, problems: list[Problem]) -> list[str]:
    failures = sum(problem.kind == "failure" for problem in problems)
    errors = sum(problem.kind == "error" for problem in problems)
    passed = max(0, total - skipped - failures - errors)
    counts = (
        f"Total: {total} | Passed: {passed} | Failed: {failures} | "
        f"Errors: {errors} | Skipped: {skipped}"
    )

    print(MANIFEST_BEGIN)
    print(counts)
    problem_count = len(problems)
    for index, problem in enumerate(problems, start=1):
        print(
            f"[{index}/{problem_count}] {problem.test_id} | {problem.kind} | "
            f"{problem.location} | {problem.message}"
        )
    print(MANIFEST_END)

    print(DETAILS_BEGIN)
    for index, problem in enumerate(problems, start=1):
        print(f"--- [{index}/{problem_count}] {problem.test_id} ---")
        print(problem.details)
    print(DETAILS_END)

    summary_lines = [
        "## Pytest failure diagnostics",
        "",
        counts,
        "",
        "| # | Test | Kind | Location | Error |",
        "|---:|---|---|---|---|",
    ]
    for index, problem in enumerate(problems, start=1):
        summary_lines.append(
            "| "
            + " | ".join(
                (
                    str(index),
                    _escape_markdown(problem.test_id),
                    _escape_markdown(problem.kind),
                    _escape_markdown(problem.location),
                    _escape_markdown(problem.message),
                )
            )
            + " |"
        )
    return summary_lines


def _workflow_warning(message: str) -> None:
    escaped = (
        message.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )
    print(f"::warning title=Pytest diagnostics unavailable::{escaped}")


def _emit_fallback(log_path: Path, *, tail_lines: int, reason: str) -> list[str]:
    _workflow_warning(reason)
    print(FALLBACK_BEGIN)
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-tail_lines:]:
            print(line)
    else:
        print("pytest log was not generated")
    print(FALLBACK_END)
    return [
        "## Pytest failure diagnostics",
        "",
        reason,
        "",
        f"Fallback tail emitted to the job log between `{FALLBACK_BEGIN}` and `{FALLBACK_END}`.",
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--detail-chars", type=int, default=1200)
    parser.add_argument("--fallback-tail-lines", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    _configure_utf8()
    args = _parse_args()

    if not args.junit.is_file():
        summary = _emit_fallback(
            args.log,
            tail_lines=max(1, args.fallback_tail_lines),
            reason="JUnit report was not generated.",
        )
        _append_github_outputs([])
        _append_summary(args.summary, summary)
        return 0

    try:
        root = ET.parse(args.junit).getroot()
        total, skipped, problems = _collect(root, detail_limit=max(200, args.detail_chars))
    except (ET.ParseError, OSError, ValueError) as exc:
        summary = _emit_fallback(
            args.log,
            tail_lines=max(1, args.fallback_tail_lines),
            reason=f"Could not parse pytest JUnit: {exc}",
        )
        _append_github_outputs([])
        _append_summary(args.summary, summary)
        return 0

    if not problems:
        summary = _emit_fallback(
            args.log,
            tail_lines=max(1, args.fallback_tail_lines),
            reason="Pytest failed but the JUnit report contains no failure or error cases.",
        )
        _append_github_outputs([])
        _append_summary(args.summary, summary)
        return 0

    _append_github_outputs(problems)
    _append_summary(args.summary, _emit_manifest(total, skipped, problems))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
