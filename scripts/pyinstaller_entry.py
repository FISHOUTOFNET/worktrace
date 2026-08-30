from __future__ import annotations

import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import TextIO


_STARTUP_LOG_NAME = "startup.log"
_MAINTENANCE_SHUTDOWN_ARGUMENT = "--shutdown-for-maintenance"
_PRIVACY_ACCEPT_ARGUMENT = "--accept-privacy-notice"
_STARTUP_CONTROL_ARGUMENT = "--configure-launch-at-login"


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


def _exception_marker(prefix: str, exc: BaseException) -> str:
    return (
        f"{prefix} exception_type={type(exc).__name__} "
        f"hresult={getattr(exc, 'hresult', None)!r} message={exc!r}"
    )


def _run_windows_probe_helper() -> int:
    """Run one closed Windows probe operation in the frozen executable."""

    if sys.stdout is None:
        sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
    if sys.stderr is None:
        sys.stderr = open(2, "w", encoding="utf-8", closefd=False)

    from worktrace.platforms.windows_probe_helper import main

    return main(sys.argv[2:])


def _run_installer_privacy_acceptance(argv: list[str]) -> int:
    """Persist one explicitly confirmed installer privacy-policy version.

    The command is intentionally narrow: only the interactive installer source
    may use it, and only the policy version shipped by this executable is
    accepted. It exits before normal application/runtime initialization.
    """

    if (
        len(argv) != 4
        or argv[0] != _PRIVACY_ACCEPT_ARGUMENT
        or argv[2] != "--source"
        or argv[3] != "installer"
    ):
        return 64

    try:
        from worktrace.services.privacy_gate_service import (
            accept_privacy_notice_version,
        )

        return 0 if accept_privacy_notice_version(argv[1]) else 65
    except Exception:
        return 1


def _run_launch_at_login_control(argv: list[str]) -> int:
    """Run one installer-owned launch-at-login state transition and exit."""

    if len(argv) != 2 or argv[0] != _STARTUP_CONTROL_ARGUMENT:
        return 64
    operation = argv[1]
    if operation not in {"enable", "disable", "migrate"}:
        return 64

    stream, _log_path = _open_startup_log()
    _write_startup_marker(stream, f"launch_at_login control start operation={operation}")
    try:
        from worktrace.platforms.windows_startup import WindowsStartupRegistration

        registration = WindowsStartupRegistration()
        if operation == "enable":
            registration.enable()
        elif operation == "disable":
            registration.disable()
        else:
            registration.migrate_legacy_registration()
        _write_startup_marker(
            stream,
            f"launch_at_login control complete operation={operation}",
        )
        return 0
    except Exception as exc:
        _write_startup_marker(
            stream,
            _exception_marker(
                f"launch_at_login control failed operation={operation}",
                exc,
            ),
        )
        if stream is not None:
            traceback.print_exc(file=stream)
            stream.flush()
        return 1
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _start_launch_at_login_repair(stream: TextIO | None) -> None:
    """Repair degraded startup registration without delaying application startup."""

    if not sys.platform.startswith("win") or not bool(getattr(sys, "frozen", False)):
        return

    def repair() -> None:
        try:
            from worktrace.platforms.windows_startup import (
                repair_launch_at_login_for_current_user,
            )

            outcome = repair_launch_at_login_for_current_user()
            if outcome == "repaired":
                _write_startup_marker(
                    stream,
                    "launch_at_login background repair outcome=repaired",
                )
        except Exception as exc:
            _write_startup_marker(
                stream,
                _exception_marker("launch_at_login background repair failed", exc),
            )
            if stream is not None:
                try:
                    traceback.print_exc(file=stream)
                    stream.flush()
                except OSError:
                    pass

    threading.Thread(
        target=repair,
        name="worktrace-launch-at-login-repair",
        daemon=True,
    ).start()


def _run_application(argv: list[str]) -> int:
    stream, log_path = _open_startup_log()
    _attach_windowed_streams(stream)
    background = "--background" in argv
    maintenance_control = _MAINTENANCE_SHUTDOWN_ARGUMENT in argv
    _write_startup_marker(
        stream,
        f"bootstrap start background={background} maintenance_control={maintenance_control}",
    )

    try:
        from worktrace.main import main

        if not maintenance_control:
            _start_launch_at_login_repair(stream)
        exit_code = int(main(argv))
    except BaseException:
        _write_startup_marker(stream, "unhandled startup exception")
        if stream is not None:
            traceback.print_exc(file=stream)
            stream.flush()
        if not background and not maintenance_control:
            _show_fatal_startup_message(_format_fatal_message(log_path=log_path))
        return 1

    if exit_code != 0:
        _write_startup_marker(stream, f"application startup exited code={exit_code}")
        if not background and not maintenance_control:
            _show_fatal_startup_message(
                _format_fatal_message(log_path=log_path, exit_code=exit_code)
            )
    return exit_code


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--windows-probe-helper":
        raise SystemExit(_run_windows_probe_helper())
    if len(sys.argv) >= 2 and sys.argv[1] == _PRIVACY_ACCEPT_ARGUMENT:
        raise SystemExit(_run_installer_privacy_acceptance(list(sys.argv[1:])))
    if len(sys.argv) >= 2 and sys.argv[1] == _STARTUP_CONTROL_ARGUMENT:
        raise SystemExit(_run_launch_at_login_control(list(sys.argv[1:])))
    raise SystemExit(_run_application(list(sys.argv[1:])))
