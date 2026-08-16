"""Fail fast when a Windows release build is using a different toolchain."""
from __future__ import annotations

import argparse
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "constraints-release.txt"
RELEASE_PYTHON_VERSION = "3.11.9"


def _pinned_packages() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirement, _, marker = line.partition(";")
        if marker.strip() and 'platform_system == "Windows"' in marker:
            if platform.system() != "Windows":
                continue
        name, separator, expected = requirement.partition("==")
        if separator != "==" or not name.strip() or not expected.strip():
            raise RuntimeError(f"Unsupported release constraint: {raw_line}")
        pins[name.strip()] = expected.strip()
    return pins


def _check_packages(names: set[str] | None) -> list[str]:
    mismatches: list[str] = []
    for package, expected in _pinned_packages().items():
        if names is not None and package.lower() not in names:
            continue
        try:
            actual = version(package)
        except PackageNotFoundError:
            mismatches.append(f"{package}: missing (expected {expected})")
            continue
        if actual != expected:
            mismatches.append(f"{package}: {actual} (expected {expected})")
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=("release", "installer"),
        default="release",
        help="Validate the full release environment or only installer prerequisites.",
    )
    args = parser.parse_args()

    mismatches: list[str] = []
    actual_python = platform.python_version()
    if actual_python != RELEASE_PYTHON_VERSION:
        mismatches.append(
            f"python: {actual_python} (expected {RELEASE_PYTHON_VERSION})"
        )

    package_scope = None if args.scope == "release" else {"pillow"}
    mismatches.extend(_check_packages(package_scope))

    if mismatches:
        print("Release environment does not match the pinned Windows baseline:")
        for mismatch in mismatches:
            print(f"- {mismatch}")
        print(
            "Install the pinned environment with: "
            "python -m pip install -r requirements-dev.txt -c constraints-release.txt"
        )
        return 1

    print(
        f"Release environment verified: Python {RELEASE_PYTHON_VERSION}, "
        f"scope={args.scope}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
