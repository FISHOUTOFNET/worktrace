#!/usr/bin/env python3
"""Render a compact, complete root-cause index from CI diagnostics."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROTOCOL = "WORKTRACE_CI_DIAGNOSTICS_V1"


def _one(value: object, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip() or "(none)"
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=8192)
    parser.add_argument("--group-limit", type=int, default=200)
    parser.add_argument("--log-lines", type=int, default=5)
    return parser.parse_args()


def _render(
    payload: dict,
    group_limit: int,
    log_lines: int,
    *,
    location_limit: int,
    message_limit: int,
) -> str:
    if payload.get("status") != "failed":
        raise ValueError("diagnostics payload must describe a failed validation")
    failures = payload.get("failures")
    groups = payload.get("root_cause_groups")
    tail = payload.get("log_tail") or []
    if not isinstance(failures, list) or not isinstance(groups, list) or not isinstance(tail, list):
        raise ValueError("diagnostics failure, group, and log fields must be lists")

    counts = payload.get("counts") or {}
    stage = _one(payload.get("failed_stage"), 40)
    shown = groups[: max(0, group_limit)]
    lines = [
        PROTOCOL,
        "summary_scope=complete_root_cause_index",
        "machine_source=artifact:diagnostics.json",
        f"revision={_one(payload.get('revision'), 80)}",
        f"stage={stage}",
        f"artifact_name={_one(payload.get('artifact_name'), 120)}",
        f"diagnostics_available={'true' if payload.get('diagnostics_available') else 'false'}",
        f"total={counts.get('total', 0)}",
        f"passed={counts.get('passed', 0)}",
        f"failed={counts.get('failed', 0)}",
        f"errors={counts.get('errors', 0)}",
        f"skipped={counts.get('skipped', 0)}",
        f"failure_count={len(failures)}",
        f"failure_signature_group_count={len(groups)}",
        f"shown_signature_group_count={len(shown)}",
        f"omitted_signature_group_count={max(0, len(groups) - len(shown))}",
    ]
    for raw in shown:
        if not isinstance(raw, dict):
            raise ValueError("root_cause_groups entries must be objects")
        tests = raw.get("affected_tests") or []
        record = {
            "id": _one(raw.get("id"), 40),
            "kind": _one(raw.get("kind"), 24),
            "location": _one(raw.get("representative_location"), location_limit),
            "message": _one(raw.get("message"), message_limit),
            "affected_test_count": len(tests) if isinstance(tests, list) else 0,
        }
        lines.append(
            "signature_group_json="
            + json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        )

    reason = _one(payload.get("reason"), 240)
    if reason != "(none)":
        lines.append(f"reason={reason}")
    if not groups and log_lines:
        excerpt = [_one(line, 180) for line in tail if str(line).strip()][-log_lines:]
        if excerpt:
            lines.extend(("LOG_EXCERPT_BEGIN", *excerpt, "LOG_EXCERPT_END"))
    raw_log = {
        "inventory": "inventory.log",
        "compile": "compile.log",
        "pytest": "pytest.log",
    }.get(stage, "validation.log")
    lines.extend(
        (
            "full_failure_index=artifact:failure-manifest.txt",
            "full_failure_details=artifact:failure-details.txt",
            f"raw_validation_log=artifact:{raw_log}",
            "artifact_contract=diagnostics.json,pytest-junit.xml,failure-manifest.txt,failure-details.txt,summary.md,raw-log",
            "",
        )
    )
    return "\n".join(lines)


def main() -> int:
    args = _args()
    if not args.input.is_file():
        raise ValueError("canonical diagnostics.json is missing")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("diagnostics payload must be a JSON object")

    limit = min(args.max_bytes, 8192)
    render_profiles = (
        (96, 96),
        (80, 64),
        (64, 32),
        (48, 0),
    )
    rendered = ""
    for location_limit, message_limit in render_profiles:
        rendered = _render(
            payload,
            args.group_limit,
            args.log_lines,
            location_limit=location_limit,
            message_limit=message_limit,
        )
        if len(rendered.encode("utf-8")) <= limit:
            break
    else:
        raise ValueError("complete root-cause index cannot fit within --max-bytes")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
