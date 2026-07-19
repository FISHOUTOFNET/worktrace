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


def _normalized_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for group in payload.get("root_cause_groups") or []:
        affected_tests = [
            _single_line(test_id, limit=300) for test_id in group.get("affected_tests") or []
        ]
        groups.append(
            {
                "id": _single_line(group.get("id"), limit=80),
                "kind": _single_line(group.get("kind"), limit=80),
                "location": _single_line(group.get("representative_location"), limit=200),
                "message": _single_line(group.get("message"), limit=500),
                "affected_test_count": len(affected_tests),
                "affected_tests": affected_tests,
                "omitted_affected_tests": 0,
            }
        )
    return groups


def _normalized_failures(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "test_id": _single_line(failure.get("test_id"), limit=300),
            "kind": _single_line(failure.get("kind"), limit=80),
            "location": _single_line(failure.get("location"), limit=200),
            "message": _single_line(failure.get("message"), limit=500),
        }
        for failure in payload.get("failures") or []
    ]


def _render(
    payload: dict[str, Any],
    *,
    groups: list[dict[str, Any]],
    failures: list[dict[str, str]],
    omitted_failures: int,
    truncated: bool,
) -> str:
    counts = payload.get("counts") or {}
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
            f"failure_count={len(payload.get('failures') or [])}",
            f"root_cause_count={len(groups)}",
            f"omitted_failure_count={omitted_failures}",
        ]
    )
    reason = _single_line(payload.get("reason"), limit=500)
    if reason != "(none)":
        lines.append(f"reason={reason}")
    lines.extend(
        [
            "root_cause_groups_json="
            + json.dumps(groups, ensure_ascii=False, separators=(",", ":")),
            "failures_json="
            + json.dumps(failures, ensure_ascii=False, separators=(",", ":")),
            f"TRUNCATED={'true' if truncated else 'false'}",
            "",
        ]
    )
    return "\n".join(lines)


def _bounded_render(payload: dict[str, Any], *, max_bytes: int) -> str:
    if max_bytes < 1024:
        raise ValueError("--max-bytes must be at least 1024")

    groups = _normalized_groups(payload)
    failures = _normalized_failures(payload)
    omitted_failures = 0
    truncated = False

    while True:
        rendered = _render(
            payload,
            groups=groups,
            failures=failures,
            omitted_failures=omitted_failures,
            truncated=truncated,
        )
        if len(rendered.encode("utf-8")) <= max_bytes:
            return rendered
        truncated = True
        if failures:
            failures.pop()
            omitted_failures += 1
            continue

        removed_test = False
        for group in reversed(groups):
            affected_tests = group["affected_tests"]
            if affected_tests:
                affected_tests.pop()
                group["omitted_affected_tests"] += 1
                removed_test = True
                break
        if removed_test:
            continue

        for group in groups:
            if group["message"] != "(omitted for size)":
                group["message"] = "(omitted for size)"
                break
        else:
            raise ValueError("diagnostics summary cannot fit within --max-bytes")


def main() -> int:
    args = _parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("diagnostics payload must be a JSON object")

    rendered = _bounded_render(payload, max_bytes=args.max_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
