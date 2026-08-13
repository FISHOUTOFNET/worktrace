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


def test_update_shutdown_lifetime_marker_outlives_runtime_cleanup() -> None:
    source = (ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")
    finally_source = source[source.index("    finally:") :]

    assert finally_source.index("update_shutdown.stop_listener()") < finally_source.index(
        "runtime.shutdown()"
    )
    assert finally_source.index("runtime.shutdown()") < finally_source.index(
        "update_shutdown.close()"
    )


def test_tray_native_window_owns_windows_session_end_messages() -> None:
    source = (ROOT / "worktrace" / "desktop" / "windows_tray.py").read_text(
        encoding="utf-8"
    )

    assert "WM_QUERYENDSESSION" in source
    assert "WM_ENDSESSION" in source
    assert "def _on_query_end_session" in source
    assert "def _on_end_session" in source
