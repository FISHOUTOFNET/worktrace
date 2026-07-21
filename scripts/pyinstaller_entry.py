from __future__ import annotations

import sys


def _run_windows_probe_helper() -> int:
    """Run one closed Windows probe operation in the frozen executable."""

    if sys.stdout is None:
        sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
    if sys.stderr is None:
        sys.stderr = open(2, "w", encoding="utf-8", closefd=False)

    from worktrace.platforms.windows_probe_helper import main

    return main(sys.argv[2:])


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--windows-probe-helper":
        raise SystemExit(_run_windows_probe_helper())
    from worktrace.main import main

    raise SystemExit(main())
