from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import TextIO


_STARTUP_LOG_NAME = "startup.log"


def _startup_log_candidates() -> list[Path]:
    local_appdata = os.environ.get("LOCALAPPDATA")
    candidates: list[Path] = []
    if local_appdata:
        candidates.append(Path(local_appdata) / "WorkTrace" / "logs" / _STARTUP_LOG_NAME)
    else:
        candidates.append(
            Path.home() / "AppData" / "Local" / "WorkTrace" / "logs" / _STARTUP_LOG_NAME
        )
    candidates.append(Path(tempfile.gettempdir()) / "WorkTrace" / _STARTUP_LOG_NAME)
    return candidates


def _open_startup_log() -> tuple[TextIO | None, Path | None]:
    for path in _startup_log_candidates():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = path.open("a", encoding="utf-8", buffering=1)
            return stream, path
        except OSError:
            continue
    return None, None


def _write_startup_marker(stream: TextIO | None, message: str) -> None:
    if stream is None:
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        stream.write(f"{timestamp} {message}\n")
        stream.flush()
    except OSError:
        pass


def _attach_windowed_streams(stream: TextIO | None) -> None:
    if stream is None:
        return
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _show_fatal_startup_message(message: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "WorkTrace", 0x00000010)
    except Exception:
        pass


def _format_fatal_message(*, log_path: Path | None, exit_code: int | None = None) -> str:
    lines = ["WorkTrace 启动失败。"]
    if exit_code is not None:
        lines.append(f"错误码：{exit_code}")
    if log_path is not None:
        lines.extend(("", "启动诊断已写入：", str(log_path)))
    else:
        lines.extend(("", "无法创建启动诊断日志，请检查当前用户的本地文件权限。"))
    return "\n".join(lines)


def _run_windows_probe_helper() -> int:
    """Run one closed Windows probe operation in the frozen executable."""

    if sys.stdout is None:
        sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
    if sys.stderr is None:
        sys.stderr = open(2, "w", encoding="utf-8", closefd=False)

    from worktrace.platforms.windows_probe_helper import main

    return main(sys.argv[2:])


def _run_application(argv: list[str]) -> int:
    stream, log_path = _open_startup_log()
    _attach_windowed_streams(stream)
    background = "--background" in argv
    _write_startup_marker(stream, f"bootstrap start background={background}")

    try:
        from worktrace.main import main

        exit_code = int(main(argv))
    except BaseException:
        _write_startup_marker(stream, "unhandled startup exception")
        if stream is not None:
            traceback.print_exc(file=stream)
            stream.flush()
        if not background:
            _show_fatal_startup_message(_format_fatal_message(log_path=log_path))
        return 1

    if exit_code != 0:
        _write_startup_marker(stream, f"application startup exited code={exit_code}")
        if not background:
            _show_fatal_startup_message(
                _format_fatal_message(log_path=log_path, exit_code=exit_code)
            )
    return exit_code


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--windows-probe-helper":
        raise SystemExit(_run_windows_probe_helper())
    raise SystemExit(_run_application(list(sys.argv[1:])))
