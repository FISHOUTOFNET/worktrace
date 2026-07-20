#!/usr/bin/env python3
"""Publish stable, API-readable CI diagnostics and failure artifacts."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1
PROTOCOL_BEGIN = "=== WORKTRACE_CI_DIAGNOSTICS_V1_BEGIN ==="
PROTOCOL_END = "=== WORKTRACE_CI_DIAGNOSTICS_V1_END ==="
FAILURES_BEGIN = "FAILURES_BEGIN"
FAILURES_END = "FAILURES_END"
GROUPS_BEGIN = "ROOT_CAUSE_GROUPS_BEGIN"
GROUPS_END = "ROOT_CAUSE_GROUPS_END"
LOG_TAIL_BEGIN = "LOG_TAIL_BEGIN"
LOG_TAIL_END = "LOG_TAIL_END"


@dataclass(frozen=True)
class Problem:
    test_id: str
    kind: str
    location: str
    message: str
    details: str


@dataclass
class RootCauseGroup:
    id: str
    signature: str
    kind: str
    message: str
    representative_location: str
    representative_details: str
    affected_tests: list[str]


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
    fallback = "(unknown)"
    for line in (text or "").splitlines():
        for pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            path = match.group("path").strip().replace("\\", "/")
            location = f"{path}:{match.group('line')}"
            normalized = f"/{path.lower()}/"
            if "/worktrace/" in normalized and "/tests/" not in normalized:
                return location
            if fallback == "(unknown)":
                fallback = location
    return fallback


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


def _normalize_signature_text(value: str) -> str:
    normalized = value.lower().replace("\\", "/")
    normalized = re.sub(r"[a-z]:/(?:[^\s|]+/)*(?:tmp|temp)/[^\s|]+", "<temp-path>", normalized)
    normalized = re.sub(r"0x[0-9a-f]+", "<hex>", normalized)
    normalized = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        "<uuid>",
        normalized,
    )
    normalized = re.sub(
        r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?z?\b",
        "<timestamp>",
        normalized,
    )
    return _single_line(normalized, limit=220)


def _group_problems(problems: list[Problem]) -> list[RootCauseGroup]:
    grouped: OrderedDict[str, RootCauseGroup] = OrderedDict()
    for problem in problems:
        signature = f"{problem.kind}|{_normalize_signature_text(problem.message)}"
        group = grouped.get(signature)
        if group is None:
            group = RootCauseGroup(
                id=f"group-{len(grouped) + 1:03d}",
                signature=signature,
                kind=problem.kind,
                message=problem.message,
                representative_location=problem.location,
                representative_details=problem.details,
                affected_tests=[],
            )
            grouped[signature] = group
        group.affected_tests.append(problem.test_id)
    return list(grouped.values())


def _counts(total: int, skipped: int, problems: list[Problem]) -> dict[str, int]:
    failures = sum(problem.kind == "failure" for problem in problems)
    errors = sum(problem.kind == "error" for problem in problems)
    return {
        "total": total,
        "passed": max(0, total - skipped - failures - errors),
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
    }


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("`", "\\`").replace("\n", " ")


def _append_summary(path: Path | None, lines: Iterable[str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for line in lines:
            stream.write(line + "\n")


def _write_text(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_github_outputs(problems: list[Problem], groups: list[RootCauseGroup]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    first_failure = problems[0].test_id if problems else ""
    first_location = problems[0].location if problems else ""
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"problem_count={len(problems)}\n")
        stream.write(f"root_cause_count={len(groups)}\n")
        stream.write(f"first_failure={_single_line(first_failure, limit=160)}\n")
        stream.write(f"first_location={_single_line(first_location, limit=120)}\n")


def _manifest_lines(counts: dict[str, int], problems: list[Problem]) -> list[str]:
    lines = [
        "Total: {total} | Passed: {passed} | Failed: {failed} | Errors: {errors} | Skipped: {skipped}".format(
            **counts
        )
    ]
    for index, problem in enumerate(problems, start=1):
        lines.append(
            f"[{index}/{len(problems)}] {problem.test_id} | {problem.kind} | "
            f"{problem.location} | {problem.message}"
        )
    return lines


def _details_lines(problems: list[Problem]) -> list[str]:
    lines: list[str] = []
    for index, problem in enumerate(problems, start=1):
        lines.extend((f"--- [{index}/{len(problems)}] {problem.test_id} ---", problem.details))
    return lines


def _summary_lines(
    counts: dict[str, int], problems: list[Problem], groups: list[RootCauseGroup]
) -> list[str]:
    lines = [
        "## Python validation diagnostics",
        "",
        "Total: {total} | Passed: {passed} | Failed: {failed} | Errors: {errors} | Skipped: {skipped}".format(
            **counts
        ),
        f"Root-cause groups: {len(groups)}",
        "",
        "### Root-cause groups",
        "",
    ]
    for group in groups:
        lines.append(
            f"- `{group.id}` ({len(group.affected_tests)}): "
            f"`{_escape_markdown(group.kind)}` — {_escape_markdown(group.message)}"
        )
    lines.extend(("", "### All failures", "", "| # | Test | Kind | Location | Error |", "|---:|---|---|---|---|"))
    for index, problem in enumerate(problems, start=1):
        lines.append(
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
    return lines


def _emit_protocol(
    *,
    revision: str,
    stage: str,
    artifact_name: str,
    counts: dict[str, int] | None,
    problems: list[Problem],
    groups: list[RootCauseGroup],
    reason: str = "",
    log_tail: list[str] | None = None,
) -> None:
    print(PROTOCOL_BEGIN)
    print(f"schema_version={SCHEMA_VERSION}")
    print(f"revision={revision or '(unknown)'}")
    print(f"failed_stage={stage}")
    print(f"artifact_name={artifact_name or '(none)'}")
    print(f"diagnostics_available={'true' if counts is not None else 'false'}")
    if counts is not None:
        for key in ("total", "passed", "failed", "errors", "skipped"):
            print(f"{key}={counts[key]}")
    print(f"failure_count={len(problems)}")
    print(f"root_cause_count={len(groups)}")
    if reason:
        print(f"reason={_single_line(reason, limit=500)}")
    print(FAILURES_BEGIN)
    empty_counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for line in _manifest_lines(counts or empty_counts, problems)[1:]:
        print(line)
    print(FAILURES_END)
    print(GROUPS_BEGIN)
    for group in groups:
        print(
            f"[{group.id}] affected={len(group.affected_tests)} | {group.kind} | "
            f"{group.representative_location} | {group.message}"
        )
        print("  representative_details:")
        for line in group.representative_details.splitlines():
            print(f"    {line}")
        for test_id in group.affected_tests:
            print(f"  - {test_id}")
    print(GROUPS_END)
    if log_tail is not None:
        print(LOG_TAIL_BEGIN)
        for line in log_tail:
            print(line)
        print(LOG_TAIL_END)
    print(PROTOCOL_END)


def _diagnostics_payload(
    *,
    revision: str,
    stage: str,
    artifact_name: str,
    counts: dict[str, int] | None,
    problems: list[Problem],
    groups: list[RootCauseGroup],
    reason: str = "",
    log_tail: list[str] | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "status": "failed",
        "failed_stage": stage,
        "artifact_name": artifact_name,
        "diagnostics_available": counts is not None,
        "reason": reason,
        "counts": counts,
        "root_cause_groups": [asdict(group) for group in groups],
        "failures": [asdict(problem) for problem in problems],
        "log_tail": list(log_tail or []),
    }


def _read_tail(path: Path, *, lines: int) -> list[str]:
    if not path.is_file():
        return [f"log file was not generated: {path}"]
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, lines) :]


def _write_outputs(
    output_dir: Path,
    *,
    payload: dict,
    manifest: list[str],
    details: list[str],
    summary: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "diagnostics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_text(output_dir / "failure-manifest.txt", manifest)
    _write_text(output_dir / "failure-details.txt", details)
    _write_text(output_dir / "summary.md", summary)


def _workflow_warning(message: str) -> None:
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::warning title=CI diagnostics fallback::{escaped}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("inventory", "compile", "pytest"), default="pytest")
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--revision", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--detail-chars", type=int, default=20000)
    parser.add_argument("--fallback-tail-lines", type=int, default=160)
    return parser.parse_args()


def _fallback(args: argparse.Namespace, reason: str) -> int:
    _workflow_warning(reason)
    tail = _read_tail(args.log, lines=args.fallback_tail_lines)
    payload = _diagnostics_payload(
        revision=args.revision,
        stage=args.stage,
        artifact_name=args.artifact_name,
        counts=None,
        problems=[],
        groups=[],
        reason=reason,
        log_tail=tail,
    )
    manifest = [f"Stage: {args.stage}", f"Reason: {reason}"]
    details = [f"Stage: {args.stage}", f"Reason: {reason}", "", *tail]
    summary = ["## Validation diagnostics", "", f"Stage: `{args.stage}`", "", reason]
    _write_outputs(args.output_dir, payload=payload, manifest=manifest, details=details, summary=summary)
    _append_github_outputs([], [])
    _append_summary(args.summary, summary)
    _emit_protocol(
        revision=args.revision,
        stage=args.stage,
        artifact_name=args.artifact_name,
        counts=None,
        problems=[],
        groups=[],
        reason=reason,
        log_tail=tail,
    )
    return 0


def main() -> int:
    _configure_utf8()
    args = _parse_args()
    if args.stage != "pytest":
        return _fallback(args, f"{args.stage} validation failed; see the captured log.")
    if args.junit is None or not args.junit.is_file():
        return _fallback(args, "JUnit report was not generated.")
    try:
        root = ET.parse(args.junit).getroot()
        total, skipped, problems = _collect(root, detail_limit=max(1000, args.detail_chars))
    except (ET.ParseError, OSError, ValueError) as exc:
        return _fallback(args, f"Could not parse pytest JUnit: {exc}")
    if not problems:
        return _fallback(args, "Pytest failed but the JUnit report contains no failure or error cases.")
    counts = _counts(total, skipped, problems)
    groups = _group_problems(problems)
    manifest = _manifest_lines(counts, problems)
    details = _details_lines(problems)
    summary = _summary_lines(counts, problems, groups)
    payload = _diagnostics_payload(
        revision=args.revision,
        stage=args.stage,
        artifact_name=args.artifact_name,
        counts=counts,
        problems=problems,
        groups=groups,
    )
    _write_outputs(args.output_dir, payload=payload, manifest=manifest, details=details, summary=summary)
    _append_github_outputs(problems, groups)
    _append_summary(args.summary, summary)
    _emit_protocol(
        revision=args.revision,
        stage=args.stage,
        artifact_name=args.artifact_name,
        counts=counts,
        problems=problems,
        groups=groups,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
