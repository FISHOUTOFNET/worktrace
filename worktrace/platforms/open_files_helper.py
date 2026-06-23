"""Standalone helper to enumerate open files for a process via psutil.

Designed to be called as a subprocess so that slow handle enumeration
does not block the main UI thread.  Works in both normal Python and
PyInstaller frozen environments.

Usage:
    python open_files_helper.py <pid>
    python -m worktrace.platforms.open_files_helper <pid>

Output: a JSON array of file-path strings on stdout.
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) < 1:
        print("[]", flush=True)
        return
    try:
        pid = int(argv[0])
    except (ValueError, TypeError):
        print("[]", flush=True)
        return
    try:
        import psutil

        paths = [item.path for item in psutil.Process(pid).open_files()]
    except Exception:
        paths = []
    print(json.dumps(paths, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
