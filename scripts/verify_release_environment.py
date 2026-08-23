"""Fail fast when a Windows build uses an unsupported Python version."""
from __future__ import annotations

import argparse
import platform
import sys

MINIMUM_PYTHON_VERSION = (3, 11)
MINIMUM_PYTHON_VERSION_TEXT = ".".join(str(value) for value in MINIMUM_PYTHON_VERSION)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=("release", "installer"),
        default="release",
        help="Validate the shared Python prerequisite for a release or installer build.",
    )
    args = parser.parse_args()

    actual = (sys.version_info.major, sys.version_info.minor)
    if actual < MINIMUM_PYTHON_VERSION:
        print(
            "Windows builds require Python "
            f">={MINIMUM_PYTHON_VERSION_TEXT}; detected {platform.python_version()}."
        )
        return 1

    print(
        f"Build environment verified: Python {platform.python_version()} "
        f"(minimum {MINIMUM_PYTHON_VERSION_TEXT}), scope={args.scope}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
