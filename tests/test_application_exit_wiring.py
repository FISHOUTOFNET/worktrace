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
    assert "exit_requested = False" in source


def test_explicit_exit_requests_runtime_stop_before_ui_teardown() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    start = source.index("        def exit_application() -> None:")
    end = source.index("        icon_path = desktop_resource_path", start)
    exit_source = source[start:end]

    assert exit_source.index("_request_runtime_shutdown(runtime)") < exit_source.index(
        "services.fd_work.shutdown()"
    )
    assert exit_source.index("services.fd_work.shutdown()") < exit_source.index(
        "shell.exit_application()"
    )
    assert "if exit_requested:\n                    return" not in exit_source


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


def test_shell_keeps_tray_until_webview_exit_is_confirmed_by_outer_cleanup() -> None:
    source = (ROOT / "worktrace" / "desktop" / "shell.py").read_text(
        encoding="utf-8"
    )
    start = source.index("    def exit_application(self) -> bool:")
    end = source.index("    def stop(self) -> None:", start)
    exit_source = source[start:end]

    assert "_submit_window_action(self._execute_exit_destroy)" in exit_source
    assert "self._tray.stop()" not in exit_source
    assert "self._exit_destroy_scheduled" in exit_source


def test_update_shutdown_lifetime_marker_outlives_runtime_cleanup() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    finally_source = source[source.index("    finally:") :]

    assert finally_source.index("update_shutdown.stop_listener()") < finally_source.index(
        "runtime.shutdown()"
    )
    assert finally_source.index("runtime.shutdown()") < finally_source.index(
        "update_shutdown.close()"
    )
    assert '_run_cleanup_step("runtime", lambda: runtime.shutdown())' in finally_source


def test_tray_native_window_owns_windows_session_end_messages() -> None:
    source = (ROOT / "worktrace" / "desktop" / "windows_tray.py").read_text(
        encoding="utf-8"
    )

    assert "WM_QUERYENDSESSION" in source
    assert "WM_ENDSESSION" in source
    assert "def _on_query_end_session" in source
    assert "def _on_end_session" in source
