from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]


def test_external_exit_sources_share_one_application_exit_path() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")

    assert "get_application_update_shutdown_coordinator" in source
    assert source.index("update_shutdown.prepare()") < source.index("runtime.initialize()")
    assert "update_shutdown.bind_shutdown_handler(exit_application)" in source
    assert "on_exit=exit_application" in source
    assert "on_session_end=exit_application" in source
    assert "exit_worker_running = False" in source
    assert 'name="WorkTraceApplicationExit"' in source


def test_explicit_exit_owns_full_terminal_cleanup_before_outer_finally() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    start = source.index("            def perform_application_exit() -> None:")
    end = source.index("            try:\n                threading.Thread(", start)
    exit_source = source[start:end]

    assert exit_source.index("_request_runtime_shutdown(runtime)") < exit_source.index(
        "services.fd_work.shutdown()"
    )
    assert exit_source.index("services.fd_work.shutdown()") < exit_source.index(
        "shell.exit_application()"
    )
    assert exit_source.index("shell.exit_application()") < exit_source.index(
        "shutdown_runtime_once"
    )
    assert '"tray_exit", lambda: tray.stop()' in exit_source
    assert '"runtime_exit", shutdown_runtime_once' in exit_source
    assert "exit_worker_running = False" in exit_source


def test_explicit_exit_coalesces_only_concurrent_workers_and_stays_retryable() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    start = source.index("        def exit_application() -> None:")
    end = source.index("        icon_path = desktop_resource_path", start)
    exit_source = source[start:end]

    assert "if exit_worker_running:\n                    return" in exit_source
    assert "exit_worker_running = True" in exit_source
    assert "finally:" in exit_source
    assert "exit_worker_running = False" in exit_source
    assert "nonlocal exit_requested" not in exit_source
    assert "exit_requested = True" not in exit_source


def test_runtime_terminal_shutdown_is_once_guarded_across_exit_and_finally() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    main_start = source.index("def main(*, background: bool = False) -> int:")
    exit_start = source.index("        def exit_application() -> None:", main_start)
    setup_source = source[main_start:exit_start]

    assert "runtime_shutdown_lock = threading.Lock()" in setup_source
    assert "runtime_shutdown_completed = False" in setup_source
    assert "def shutdown_runtime_once() -> None:" in setup_source
    assert "if runtime_shutdown_completed:\n                return" in setup_source
    assert setup_source.index("runtime.shutdown()") < setup_source.index(
        "runtime_shutdown_completed = True"
    )


def test_window_close_remains_hide_to_tray_not_runtime_shutdown() -> None:
    source = (ROOT / "worktrace" / "desktop" / "shell.py").read_text(
        encoding="utf-8"
    )
    start = source.index("    def handle_window_closing(self) -> bool:")
    end = source.index("    def hide_window(self) -> bool:", start)
    close_source = source[start:end]

    assert "self.state = ShellState.HIDDEN" in close_source
    assert "return False" in close_source
    assert "request_shutdown" not in close_source


def test_shell_terminal_exit_destroys_main_window_before_releasing_tray() -> None:
    source = (ROOT / "worktrace" / "desktop" / "shell.py").read_text(
        encoding="utf-8"
    )
    start = source.index("    def exit_application(self) -> bool:")
    end = source.index("    def stop(self) -> None:", start)
    exit_source = source[start:end]

    assert exit_source.index("self._window.destroy()") < exit_source.index("self.stop()")
    assert "_submit_window_action" not in exit_source
    assert "self._exit_completed" in exit_source
    assert "return False" in exit_source


def test_outer_cleanup_remains_idempotent_terminal_fallback() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    cleanup_start = source.index('        logging.info("application cleanup begin")')
    cleanup_end = source.index('        logging.info("application cleanup end")', cleanup_start)
    finally_source = source[cleanup_start:cleanup_end]

    assert finally_source.index("update_shutdown.stop_listener()") < finally_source.index(
        '"runtime", shutdown_runtime_once'
    )
    assert finally_source.index('"runtime", shutdown_runtime_once') < finally_source.index(
        "update_shutdown.close()"
    )
    assert '_run_cleanup_step("desktop_shell", lambda: shell.stop())' in finally_source
    assert '_run_cleanup_step("runtime", shutdown_runtime_once)' in finally_source


def test_tray_native_window_owns_windows_session_end_messages() -> None:
    source = (ROOT / "worktrace" / "desktop" / "windows_tray.py").read_text(
        encoding="utf-8"
    )

    assert "WM_QUERYENDSESSION" in source
    assert "WM_ENDSESSION" in source
    assert "def _on_query_end_session" in source
    assert "def _on_end_session" in source
