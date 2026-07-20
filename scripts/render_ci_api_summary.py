#!/usr/bin/env python3
"""Render a concise human summary from the canonical CI diagnostics artifact."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PROTOCOL = "WORKTRACE_CI_DIAGNOSTICS_V1"
DEFAULT_MAX_BYTES = 8192
DEFAULT_GROUP_LIMIT = 5
DEFAULT_LOG_LINES = 5


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
    parser.add_argument("--group-limit", type=int, default=DEFAULT_GROUP_LIMIT)
    parser.add_argument("--log-lines", type=int, default=DEFAULT_LOG_LINES)
    return parser.parse_args()


def _validate_payload(payload: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "revision",
        "status",
        "failed_stage",
        "diagnostics_available",
        "root_cause_groups",
        "failures",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError("diagnostics payload missing fields: " + ", ".join(missing))
    if payload.get("status") != "failed":
        raise ValueError("diagnostics payload must describe a failed validation")
    if not isinstance(payload.get("root_cause_groups"), list):
        raise ValueError("root_cause_groups must be a list")
    if not isinstance(payload.get("failures"), list):
        raise ValueError("failures must be a list")
    if not isinstance(payload.get("log_tail") or [], list):
        raise ValueError("log_tail must be a list")


def _group_record(raw_group: object) -> dict[str, object]:
    if not isinstance(raw_group, dict):
        raise ValueError("root_cause_groups entries must be objects")
    affected_tests = raw_group.get("affected_tests") or []
    if not isinstance(affected_tests, list):
        raise ValueError("affected_tests must be a list")
    return {
        "id": _single_line(raw_group.get("id"), limit=40),
        "kind": _single_line(raw_group.get("kind"), limit=40),
        "location": _single_line(raw_group.get("representative_location"), limit=140),
        "message": _single_line(raw_group.get("message"), limit=180),
        "affected_test_count": len(affected_tests),
    }


def _raw_log_name(stage: str) -> str:
    return {
        "inventory": "inventory.log",
        "compile": "compile.log",
        "pytest": "pytest.log",
    }.get(stage, "validation.log")


def _render(
    payload: dict[str, Any],
    *,
    groups: list[dict[str, object]],
    log_excerpt: list[str],
) -> str:
    counts = payload.get("counts") or {}
    total_groups = len(payload.get("root_cause_groups") or [])
    omitted_groups = max(0, total_groups - len(groups))
    stage = _single_line(payload.get("failed_stage"), limit=40)
    lines = [
        PROTOCOL,
        "summary_scope=human",
        "machine_source=artifact:diagnostics.json",
        f"revision={_single_line(payload.get('revision'), limit=80)}",
        f"failed_stage={stage}",
        f"artifact_name={_single_line(payload.get('artifact_name'), limit=120)}",
        f"diagnostics_available={'true' if payload.get('diagnostics_available') else 'false'}",
        f"total={counts.get('total', 0)}",
        f"passed={counts.get('passed', 0)}",
        f"failed={counts.get('failed', 0)}",
        f"errors={counts.get('errors', 0)}",
        f"skipped={counts.get('skipped', 0)}",
        f"failure_count={len(payload.get('failures') or [])}",
        f"failure_signature_group_count={total_groups}",
        f"shown_signature_group_count={len(groups)}",
        f"omitted_signature_group_count={omitted_groups}",
    ]
    lines.extend(
        "signature_group_json="
        + json.dumps(group, ensure_ascii=False, separators=(",", ":"))
        for group in groups
    )
    reason = _single_line(payload.get("reason"), limit=240)
    if reason != "(none)":
        lines.append(f"reason={reason}")
    if log_excerpt:
        lines.append("LOG_EXCERPT_BEGIN")
        lines.extend(log_excerpt)
        lines.append("LOG_EXCERPT_END")
    lines.extend(
        (
            "full_failure_index=artifact:failure-manifest.txt",
            "full_failure_details=artifact:failure-details.txt",
            f"raw_validation_log=artifact:{_raw_log_name(stage)}",
            "artifact_contract=diagnostics.json,pytest-junit.xml,failure-manifest.txt,failure-details.txt,summary.md,raw-log",
            "",
        )
    )
    return "\n".join(lines)


def _bounded_render(
    payload: dict[str, Any],
    *,
    max_bytes: int,
    group_limit: int,
    log_lines: int,
) -> str:
    if max_bytes < 2048:
        raise ValueError("--max-bytes must be at least 2048")
    if group_limit < 0 or log_lines < 0:
        raise ValueError("--group-limit and --log-lines must be non-negative")
    _validate_payload(payload)

    all_groups = [_group_record(group) for group in payload.get("root_cause_groups") or []]
    raw_tail = [
        _single_line(line, limit=180)
        for line in (payload.get("log_tail") or [])
        if str(line).strip()
    ]

    initial_group_count = min(group_limit, len(all_groups))
    initial_log_count = min(log_lines, len(raw_tail)) if not all_groups else 0
    for group_count in range(initial_group_count, -1, -1):
        for log_count in range(initial_log_count, -1, -1):
            rendered = _render(
                payload,
                groups=all_groups[:group_count],
                log_excerpt=raw_tail[-log_count:] if log_count else [],
            )
            if len(rendered.encode("utf-8")) <= max_bytes:
                return rendered
    raise ValueError("human diagnostics summary cannot fit within --max-bytes")


def main() -> int:
    args = _parse_args()
    if not args.input.is_file():
        raise ValueError("canonical diagnostics.json is missing")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("diagnostics payload must be a JSON object")
    rendered = _bounded_render(
        payload,
        max_bytes=args.max_bytes,
        group_limit=args.group_limit,
        log_lines=args.log_lines,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
