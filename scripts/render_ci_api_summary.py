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
_MAX_DETAIL_LINES = 120
_MAX_DETAIL_LINE_CHARS = 500


def _single_line(value: object, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if not compact:
        return "(none)"
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _detail_lines(value: object) -> list[str]:
    if isinstance(value, list):
        raw_lines = [str(line) for line in value]
    else:
        raw_lines = str(value or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    lines = [
        _single_line(line, limit=_MAX_DETAIL_LINE_CHARS)
        for line in raw_lines
        if str(line).strip()
    ]
    return lines[:_MAX_DETAIL_LINES] or ["(no traceback details)"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
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


def _failure_details(payload: dict[str, Any]) -> dict[str, object]:
    result: dict[str, object] = {}
    for failure in payload.get("failures") or []:
        if not isinstance(failure, dict):
            continue
        test_id = str(failure.get("test_id") or "")
        if test_id and test_id not in result:
            result[test_id] = failure.get("details")
    return result


def _normalized_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    details_by_test = _failure_details(payload)
    groups: list[dict[str, Any]] = []
    for raw_group in payload.get("root_cause_groups") or []:
        if not isinstance(raw_group, dict):
            raise ValueError("root_cause_groups entries must be objects")
        affected_tests = [
            _single_line(test_id, limit=260)
            for test_id in raw_group.get("affected_tests") or []
        ]
        representative_details = raw_group.get("representative_details")
        if not representative_details and affected_tests:
            representative_details = details_by_test.get(affected_tests[0])
        groups.append(
            {
                "id": _single_line(raw_group.get("id"), limit=40),
                "kind": _single_line(raw_group.get("kind"), limit=40),
                "location": _single_line(raw_group.get("representative_location"), limit=160),
                "message": _single_line(raw_group.get("message"), limit=240),
                "representative_details": _detail_lines(representative_details),
                "affected_test_count": len(affected_tests),
                "affected_tests": affected_tests,
                "omitted_affected_tests": 0,
                "omitted_detail_lines": 0,
            }
        )
    return groups


def _index_group(group: dict[str, Any]) -> dict[str, object]:
    """Return the compact first-pass record that must expose every root cause."""

    return {
        "id": group["id"],
        "kind": group["kind"],
        "location": group["location"],
        "message": group["message"],
        "affected_test_count": group["affected_test_count"],
    }


def _normalized_log_tail(payload: dict[str, Any]) -> list[str]:
    raw_tail = payload.get("log_tail") or []
    if not isinstance(raw_tail, list):
        raise ValueError("log_tail must be a list")
    return [_single_line(line, limit=500) for line in raw_tail[-160:]]


def _render(
    payload: dict[str, Any],
    *,
    groups: list[dict[str, Any]],
    log_tail: list[str],
    truncated: bool,
) -> str:
    counts = payload.get("counts") or {}
    lines = [
        PROTOCOL,
        f"schema_version={payload.get('schema_version')}",
        f"revision={_single_line(payload.get('revision'), limit=80)}",
        f"failed_stage={_single_line(payload.get('failed_stage'), limit=40)}",
        f"artifact_name={_single_line(payload.get('artifact_name'), limit=120)}",
        f"diagnostics_available={'true' if payload.get('diagnostics_available') else 'false'}",
        f"total={counts.get('total', 0)}",
        f"passed={counts.get('passed', 0)}",
        f"failed={counts.get('failed', 0)}",
        f"errors={counts.get('errors', 0)}",
        f"skipped={counts.get('skipped', 0)}",
        f"failure_count={len(payload.get('failures') or [])}",
        f"root_cause_count={len(groups)}",
        "ROOT_CAUSE_INDEX_BEGIN",
    ]
    lines.extend(
        "cause_json=" + json.dumps(_index_group(group), ensure_ascii=False, separators=(",", ":"))
        for group in groups
    )
    lines.append("ROOT_CAUSE_INDEX_END")
    reason = _single_line(payload.get("reason"), limit=240)
    if reason != "(none)":
        lines.append(f"reason={reason}")
    if log_tail:
        lines.append("LOG_TAIL_BEGIN")
        lines.extend(log_tail)
        lines.append("LOG_TAIL_END")
    lines.append("ROOT_CAUSE_GROUPS_BEGIN")
    lines.extend(
        "group_json=" + json.dumps(group, ensure_ascii=False, separators=(",", ":"))
        for group in groups
    )
    lines.extend(("ROOT_CAUSE_GROUPS_END", f"TRUNCATED={'true' if truncated else 'false'}", ""))
    return "\n".join(lines)


def _bounded_render(payload: dict[str, Any], *, max_bytes: int) -> str:
    if max_bytes < 1024:
        raise ValueError("--max-bytes must be at least 1024")
    _validate_payload(payload)
    groups = _normalized_groups(payload)
    log_tail = _normalized_log_tail(payload)
    truncated = False

    while True:
        rendered = _render(payload, groups=groups, log_tail=log_tail, truncated=truncated)
        if len(rendered.encode("utf-8")) <= max_bytes:
            return rendered
        truncated = True

        removed = False
        for group in reversed(groups):
            if group["affected_tests"]:
                group["affected_tests"].pop()
                group["omitted_affected_tests"] += 1
                removed = True
                break
        if removed:
            continue

        for group in reversed(groups):
            details = group["representative_details"]
            if len(details) > 1:
                details.pop()
                group["omitted_detail_lines"] += 1
                removed = True
                break
            if details and details[0] != "(traceback omitted for size)":
                details[0] = "(traceback omitted for size)"
                group["omitted_detail_lines"] += 1
                removed = True
                break
        if removed:
            continue

        if log_tail:
            log_tail.pop(0)
            continue

        for group in groups:
            if group["message"] != "(omitted for size)":
                group["message"] = "(omitted for size)"
                removed = True
                break
        if removed:
            continue
        raise ValueError("diagnostics summary cannot fit within --max-bytes")


def main() -> int:
    args = _parse_args()
    if not args.input.is_file():
        raise ValueError("canonical diagnostics.json is missing")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("diagnostics payload must be a JSON object")
    rendered = _bounded_render(payload, max_bytes=args.max_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
