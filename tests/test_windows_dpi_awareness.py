from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from worktrace.platforms import windows_dpi


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _fake_user32(*, current: int = 1, equal: object = False, set_result: bool = False):
    return SimpleNamespace(
        GetThreadDpiAwarenessContext=Mock(return_value=current),
        AreDpiAwarenessContextsEqual=Mock(return_value=equal),
        SetProcessDpiAwarenessContext=Mock(return_value=set_result),
    )


def test_non_windows_is_noop():
    with (
        patch.object(windows_dpi.sys, "platform", "linux"),
        patch.object(windows_dpi, "_load_user32") as load_user32,
    ):
        assert windows_dpi.configure_process_dpi_awareness() is True
    load_user32.assert_not_called()


def test_existing_per_monitor_v2_context_is_preserved():
    user32 = _fake_user32(equal=True)
    with (
        patch.object(windows_dpi.sys, "platform", "win32"),
        patch.object(windows_dpi, "_load_user32", return_value=user32),
    ):
        assert windows_dpi.configure_process_dpi_awareness() is True
    user32.SetProcessDpiAwarenessContext.assert_not_called()


def test_process_is_upgraded_to_per_monitor_v2_before_ui_startup():
    user32 = _fake_user32(equal=False, set_result=True)
    with (
        patch.object(windows_dpi.sys, "platform", "win32"),
        patch.object(windows_dpi, "_load_user32", return_value=user32),
    ):
        assert windows_dpi.configure_process_dpi_awareness() is True
    target = user32.SetProcessDpiAwarenessContext.call_args.args[0]
    assert target.value == windows_dpi._target_context().value


def test_manifest_owned_context_is_accepted_after_access_denied():
    user32 = _fake_user32(equal=Mock(side_effect=[False, True]), set_result=False)
    with (
        patch.object(windows_dpi.sys, "platform", "win32"),
        patch.object(windows_dpi, "_load_user32", return_value=user32),
        patch.object(windows_dpi, "_last_error", return_value=5),
    ):
        assert windows_dpi.configure_process_dpi_awareness() is True


def test_unexpected_dpi_configuration_failure_is_non_fatal():
    user32 = _fake_user32(equal=False, set_result=False)
    with (
        patch.object(windows_dpi.sys, "platform", "win32"),
        patch.object(windows_dpi, "_load_user32", return_value=user32),
        patch.object(windows_dpi, "_last_error", return_value=87),
    ):
        assert windows_dpi.configure_process_dpi_awareness() is False
