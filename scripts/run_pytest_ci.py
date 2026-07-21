#!/usr/bin/env python3
"""Run pytest with artifact-only output and bounded progress heartbeats."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_PROGRESS_ENV = "WORKTRACE_PYTEST_PROGRESS_FILE"
_completed = 0
_total = 0
_current = ""


def _progress_path() -> Path | None:
    value = os.environ.get(_PROGRESS_ENV, "").strip()
    return Path(value) if value else None


def _write_progress(*, status: str) -> None:
    path = _progress_path()
    if path is None:
        return
    payload = {
        "status": status,
        "completed": _completed,
        "total": _total,
        "current": _current,
        "updated_at_epoch": time.time(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    _replace_progress_file(temporary, path)


def _replace_progress_file(temporary: Path, target: Path) -> None:
    """Replace the progress file, tolerating transient Windows file locks.

    The runner process polls the progress file via _read_progress while the
    pytest subprocess writes it here. On Windows, Path.replace fails with
    PermissionError when another handle holds the target open for reading.
    The progress file is best-effort; retrying briefly lets the read finish
    rather than crashing pytest_sessionfinish and losing failure output.
    """
    last_error: OSError | None = None
    for attempt in range(5):
        try:
            temporary.replace(target)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.02 * (attempt + 1))
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
    # Last attempt failed; the runner still emits a final heartbeat, so a
    # stale progress file is acceptable. Silence the error rather than
    # tearing down pytest_sessionfinish and masking test failure output.
    del last_error


def pytest_collection_finish(session: Any) -> None:
    global _total
    _total = len(session.items)
    _write_progress(status="running")


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    del location
    global _current
    _current = nodeid
    _write_progress(status="running")


def pytest_runtest_logfinish(nodeid: str, location: tuple[str, int | None, str]) -> None:
    del location
    global _completed, _current
    _completed += 1
    _current = nodeid
    _write_progress(status="running")


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    del session, exitstatus
    global _current
    _current = ""
    _write_progress(status="finished")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=60.0)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.pytest_args[:1] == ["--"]:
        args.pytest_args = args.pytest_args[1:]
    if not args.pytest_args:
        parser.error("pytest arguments are required after --")
    if args.heartbeat_seconds < 0.05:
        parser.error("--heartbeat-seconds must be at least 0.05")
    return args


def _read_progress(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _one_line(value: object, *, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip() or "(collecting)"
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _emit_heartbeat(
    progress_path: Path,
    *,
    started_at: float,
    forced_status: str | None = None,
) -> None:
    payload = _read_progress(progress_path)
    status = forced_status or str(payload.get("status") or "starting")
    completed = int(payload.get("completed") or 0)
    total_value = payload.get("total")
    total = int(total_value) if isinstance(total_value, int) and total_value > 0 else "unknown"
    current = _one_line(payload.get("current"))
    elapsed = max(0, int(time.monotonic() - started_at))
    print(
        f"pytest_progress status={status} completed={completed} total={total} "
        f"current={current} elapsed_seconds={elapsed}",
        flush=True,
    )


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    args = _parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.progress.parent.mkdir(parents=True, exist_ok=True)
    args.progress.unlink(missing_ok=True)

    environment = os.environ.copy()
    environment[_PROGRESS_ENV] = str(args.progress.resolve())
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "scripts.run_pytest_ci",
        *args.pytest_args,
    ]

    started_at = time.monotonic()
    _emit_heartbeat(args.progress, started_at=started_at)
    with args.log.open("w", encoding="utf-8", errors="replace", newline="\n") as log_stream:
        process = subprocess.Popen(
            command,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            env=environment,
            text=True,
        )
        next_heartbeat = started_at + args.heartbeat_seconds
        try:
            while process.poll() is None:
                now = time.monotonic()
                if now >= next_heartbeat:
                    _emit_heartbeat(args.progress, started_at=started_at)
                    next_heartbeat = now + args.heartbeat_seconds
                time.sleep(min(0.25, max(0.05, next_heartbeat - time.monotonic())))
        except KeyboardInterrupt:
            _terminate(process)
            return 130

    return_code = int(process.returncode or 0)
    _emit_heartbeat(args.progress, started_at=started_at, forced_status="finished")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
