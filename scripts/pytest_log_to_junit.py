#!/usr/bin/env python3
"""Recover a partial JUnit report from a streamed pytest log after hard termination."""

from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

_STATUS_LINE = re.compile(
    r"^(?P<test>tests/.+?)\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)"
    r"(?:\s+\[\s*\d+%\])?\s*$"
)
_TIMEOUT_LINE = re.compile(
    r"^(?P<test>tests/.+?)\s+\+{10,}\s*Timeout\s*\+{10,}\s*$"
)


@dataclass(frozen=True)
class ObservedCase:
    test_id: str
    status: str
    details: str = ""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    return parser.parse_args()


def _split_test_id(test_id: str) -> tuple[str, str]:
    normalized = test_id.strip().replace("\\", "/")
    if "::" not in normalized:
        return "pytest.log", normalized
    path, name = normalized.split("::", 1)
    class_name = path.removesuffix(".py").replace("/", ".")
    return class_name, name


def _collect(log_text: str) -> list[ObservedCase]:
    lines = log_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    observed: OrderedDict[str, ObservedCase] = OrderedDict()

    for index, line in enumerate(lines):
        status_match = _STATUS_LINE.match(line)
        if status_match:
            test_id = status_match.group("test").strip()
            observed[test_id] = ObservedCase(
                test_id=test_id,
                status=status_match.group("status"),
                details=line,
            )
            continue

        timeout_match = _TIMEOUT_LINE.match(line)
        if timeout_match:
            test_id = timeout_match.group("test").strip()
            stack_lines = [line]
            for trailing in lines[index + 1 :]:
                stack_lines.append(trailing)
                if trailing.startswith("+++++++++++++++++++++++++++++++++++ Timeout"):
                    break
            observed[test_id] = ObservedCase(
                test_id=test_id,
                status="TIMEOUT",
                details="\n".join(stack_lines),
            )

    return list(observed.values())


def _write_junit(
    cases: list[ObservedCase],
    *,
    output: Path,
    timeout_seconds: int,
) -> None:
    failures = sum(case.status == "FAILED" for case in cases)
    errors = sum(case.status in {"ERROR", "TIMEOUT"} for case in cases)
    skipped = sum(case.status in {"SKIPPED", "XFAIL"} for case in cases)
    suite = ET.Element(
        "testsuite",
        name="pytest-log-recovery",
        tests=str(len(cases)),
        failures=str(failures),
        errors=str(errors),
        skipped=str(skipped),
    )
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="partial", value="true")
    ET.SubElement(properties, "property", name="source", value="pytest.log")

    for case in cases:
        class_name, test_name = _split_test_id(case.test_id)
        testcase = ET.SubElement(
            suite,
            "testcase",
            classname=class_name,
            name=test_name,
        )
        if case.status == "FAILED":
            child = ET.SubElement(
                testcase,
                "failure",
                message=(
                    "pytest reported failure before the process was terminated; "
                    "traceback was not finalized"
                ),
            )
            child.text = case.details
        elif case.status == "ERROR":
            child = ET.SubElement(
                testcase,
                "error",
                message=(
                    "pytest reported an error before the process was terminated; "
                    "traceback was not finalized"
                ),
            )
            child.text = case.details
        elif case.status == "TIMEOUT":
            child = ET.SubElement(
                testcase,
                "error",
                message=f"pytest-timeout: test exceeded {timeout_seconds} seconds",
            )
            child.text = case.details
        elif case.status in {"SKIPPED", "XFAIL"}:
            ET.SubElement(testcase, "skipped", message=case.status.lower())

    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(output, encoding="utf-8", xml_declaration=True)


def main() -> int:
    args = _parse_args()
    if not args.log.is_file():
        raise SystemExit(f"pytest log does not exist: {args.log}")
    cases = _collect(args.log.read_text(encoding="utf-8", errors="replace"))
    if not cases:
        raise SystemExit("pytest log contains no recoverable test results")
    _write_junit(
        cases,
        output=args.output,
        timeout_seconds=max(1, args.timeout_seconds),
    )
    print(
        f"Recovered partial JUnit with {len(cases)} observed tests at {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
