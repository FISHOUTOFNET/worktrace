#!/usr/bin/env python3
"""Render bounded, API-readable CI diagnostics from the canonical JSON artifact."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PROTOCOL = "WORKTRACE_CI_DIAGNOSTICS_V1"
DEFAULT_MAX_BYTES = 65536
_TRUNCATION_RESERVE = 256


def _single_line(value: object, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if not compact:
        return "(none)"
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    return parser.parse_args()


def _header_lines(payload: dict[str, Any]) -> list[str]:
    counts = payload.get("counts") or {}
    failures = payload.get("failures") or []
    groups = payload.get("root_cause_groups") or []
    lines = [
        PROTOCOL,
        f"schema_version={payload.get('schema_version', '(unknown)')}",
        f"revision={_single_line(payload.get('revision'), limit=160)}",
        f"failed_stage={_single_line(payload.get('failed_stage'), limit=80)}",
        f"artifact_name={_single_line(payload.get('artifact_name'), limit=180)}",
        f"diagnostics_available={'true' if payload.get('diagnostics_available') else 'false'}",
    ]
    for key in ("total", "passed", "failed", "errors", "skipped"):
        lines.append(f"{key}={counts.get(key, 0)}")
    lines.extend(
        [
            f"failure_count={len(failures)}",
            f"root_cause_count={len(groups)}",
        ]
    )
    reason = _single_line(payload.get("reason"), limit=500)
    if reason != "(none)":
        lines.append(f"reason={reason}")
    return lines


def _group_lines(payload: dict[str, Any]) -> list[str]:
    lines = ["ROOT_CAUSE_GROUPS_BEGIN"]
    for group in payload.get("root_cause_groups") or []:
        tests = group.get("affected_tests") or []
        lines.extend(
            [
                f"[{_single_line(group.get('id'), limit=80)}]",
                f"kind={_single_line(group.get('kind'), limit=80)}",
                f"location={_single_line(group.get('representative_location'), limit=200)}",
                f"message={_single_line(group.get('message'), limit=500)}",
                f"affected_test_count={len(tests)}",
            ]
        )
        lines.extend(f"- {_single_line(test_id, limit=300)}" for test_id in tests)
    lines.append("ROOT_CAUSE_GROUPS_END")
    return lines


def _failure_lines(payload: dict[str, Any]) -> list[str]:
    failures = payload.get("failures") or []
    lines = ["ALL_FAILURES_BEGIN"]
    for index, failure in enumerate(failures, start=1):
        lines.append(
            f"[{index}/{len(failures)}] "
            f"{_single_line(failure.get('test_id'), limit=300)} | "
            f"{_single_line(failure.get('kind'), limit=80)} | "
            f"{_single_line(failure.get('location'), limit=200)} | "
            f"{_single_line(failure.get('message'), limit=500)}"
        )
    lines.append("ALL_FAILURES_END")
    return lines


def _bounded_text(lines: list[str], *, max_bytes: int) -> str:
    if max_bytes < 1024:
        raise ValueError("--max-bytes must be at least 1024")

    complete = "\n".join([*lines, "TRUNCATED=false", ""])
    if len(complete.encode("utf-8")) <= max_bytes:
        return complete

    kept: list[str] = []
    budget = max_bytes - _TRUNCATION_RESERVE
    for line in lines:
        candidate = "\n".join([*kept, line, ""])
        if len(candidate.encode("utf-8")) > budget:
            break
        kept.append(line)

    truncated = "\n".join(
        [
            *kept,
            "TRUNCATED=true",
            "See diagnostics.json and failure-details.txt in the named artifact for complete data.",
            "",
        ]
    )
    encoded = truncated.encode("utf-8")
    if len(encoded) > max_bytes:
        encoded = encoded[:max_bytes]
        truncated = encoded.decode("utf-8", errors="ignore")
    return truncated


def main() -> int:
    args = _parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("diagnostics payload must be a JSON object")

    lines = [
        *_header_lines(payload),
        *_group_lines(payload),
        *_failure_lines(payload),
    ]
    rendered = _bounded_text(lines, max_bytes=args.max_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
