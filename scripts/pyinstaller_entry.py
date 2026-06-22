from __future__ import annotations

import sys


def _run_open_files_helper() -> None:
    """Run the open-files helper when invoked via --open-files-helper <pid>."""
    import os

    # In PyInstaller GUI mode (console=False), sys.stdout is None.
    # Reconnect to the OS-level stdout file descriptor so that
    # subprocess.run(capture_output=True) can read the output.
    if sys.stdout is None:
        sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
    if sys.stderr is None:
        sys.stderr = open(2, "w", encoding="utf-8", closefd=False)

    from worktrace.platforms.open_files_helper import main

    main()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--open-files-helper":
        _run_open_files_helper()
        raise SystemExit(0)
    from worktrace.main import main

    raise SystemExit(main())
