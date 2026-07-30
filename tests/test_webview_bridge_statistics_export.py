"""WebView bridge statistics export contract tests.

Tests the bridge's transport-layer responsibilities for CSV export without
using a real database, real ticket computation, or real file output:

- ticket presence validation (before save dialog)
- date/range transport-shape validation
- save dialog return-type handling (string, tuple, list, empty, exception)
- window absence handling
- capability error code -> Chinese message mapping
- unknown exception collapse
- payload never leaks full path or sensitive fields
- bridge does not import backend internals
- summary method remains read-only (no dialog, no file)
- set_window does not start GUI
- error message table stability

Uses FakeStatisticsCapability and explicit fake windows. No SQLite fixture,
real ticket computation, service database access, or CSV output.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.support.application import FakeStatisticsCapability, build_test_bridge
from worktrace.api.export_api import StatisticsExportError

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

VALID_TICKET = "valid-ticket-for-bridge-contract"

SENSITIVE_KEYS = (
    "window_title",
    "file_path_hint",
    "full_path",
    "clipboard",
    "note",
    "traceback",
    "exception",
    "stack",
    "sql",
)

SENSITIVE_TOKENS = (
    "traceback",
    "select",
    "secret",
    "c:\\",
    "runtimeerror",
    "window_title",
    "file_path_hint",
    "note",
)


def _assert_no_sensitive_keys(payload, label: str = "payload") -> None:
    if isinstance(payload, dict):
        for key in SENSITIVE_KEYS:
            assert key not in payload, (
                f"{label} must not expose sensitive key '{key}'; "
                f"got keys: {sorted(payload.keys())}"
            )
        for value in payload.values():
            _assert_no_sensitive_keys(value, label)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_sensitive_keys(item, label)


class _FakeDialogWindow:
    """Explicit fake window for save-dialog contract tests."""

    def __init__(self, return_value=None, raise_exc=None):
        self._return_value = return_value
        self._raise_exc = raise_exc
        self.dialog_calls = 0

    def create_file_dialog(self, *args, **kwargs):
        self.dialog_calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._return_value


def _bridge_with_fake_capability(
    *,
    export_return=None,
    export_side_effect=None,
    format_return="00:30:00",
):
    """Build a bridge backed by FakeStatisticsCapability."""
    statistics = FakeStatisticsCapability()
    if export_return is not None:
        statistics.export_statistics_csv_return = export_return
    if export_side_effect is not None:
        statistics.export_statistics_csv_side_effect = export_side_effect
    statistics.format_export_duration_return = format_return
    return build_test_bridge(statistics=statistics), statistics


# -- Ticket validation (before save dialog) ---------------------------------


@pytest.mark.parametrize("ticket", [None, "", "   "])
def test_bridge_export_blank_ticket_rejected_before_dialog(ticket):
    """A missing, empty, or whitespace ticket must not open the save dialog."""
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    window = _FakeDialogWindow(return_value="unused.csv")
    bridge.set_window(window)
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", ticket)
    assert result["ok"] is False
    assert result["error"] == "统计数据已更新，请重新加载后导出"
    assert result["cancelled"] is False
    assert window.dialog_calls == 0
    assert statistics.export_statistics_csv_calls == []


def test_bridge_export_missing_ticket_does_not_call_service():
    """A missing ticket must not call the export capability at all."""
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_FakeDialogWindow(return_value="unused.csv"))
    result = bridge.export_statistics_csv("2026-06-25", "2026-06-25", None)
    assert result["ok"] is False
    assert statistics.export_statistics_csv_calls == []


def test_bridge_export_wrong_ticket_rejected_by_capability():
    """A syntactically valid but semantically wrong ticket is rejected by the capability."""
    statistics = FakeStatisticsCapability()
    statistics.export_statistics_csv_side_effect = StatisticsExportError(
        "stale_statistics_snapshot"
    )
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_FakeDialogWindow(return_value="wrong.csv"))
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", "wrong-revision"
    )
    assert result["ok"] is False
    assert result["error"] == "统计数据已更新，请重新加载后导出"
    assert result["cancelled"] is False


# -- Date/range transport-shape validation ----------------------------------


@pytest.mark.parametrize(
    ("date_from", "date_to", "message"),
    [
        ("not-a-date", "2026-06-25", "请选择有效日期"),
        (True, "2026-06-25", "请选择有效日期"),
        (None, "2026-06-25", "请选择有效日期"),
    ],
)
def test_bridge_export_invalid_inputs_return_chinese(date_from, date_to, message):
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_FakeDialogWindow(return_value="unused.csv"))
    result = bridge.export_statistics_csv(date_from, date_to, VALID_TICKET)
    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["error"] == message
    assert statistics.export_statistics_csv_calls == []


# -- Save dialog cancellation and return-type handling ----------------------


@pytest.mark.parametrize("return_value", [None, (), []])
def test_bridge_export_cancelled_does_not_call_service(return_value):
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_FakeDialogWindow(return_value=return_value))
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result == {"ok": False, "cancelled": True, "error": "已取消导出"}
    assert statistics.export_statistics_csv_calls == []


def test_bridge_export_dialog_returns_single_string():
    """When the dialog returns a bare string, the bridge extracts it and calls the capability."""
    bridge, statistics = _bridge_with_fake_capability(
        export_return={
            "filename": "report.csv",
            "activity_count": 1,
            "duration_seconds": 1800,
        },
    )
    bridge.set_window(_FakeDialogWindow(return_value="output/report.csv"))
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is True
    assert result["filename"] == "report.csv"
    assert result["activity_count"] == 1
    assert result["duration"] == "00:30:00"
    assert result["cancelled"] is False
    assert len(statistics.export_statistics_csv_calls) == 1


def test_bridge_export_dialog_returns_list_with_path():
    """When the dialog returns a list, the bridge takes the first element."""
    bridge, statistics = _bridge_with_fake_capability(
        export_return={
            "filename": "report.csv",
            "activity_count": 1,
            "duration_seconds": 1800,
        },
    )
    bridge.set_window(_FakeDialogWindow(return_value=["output/report.csv"]))
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is True
    assert result["filename"] == "report.csv"


def test_bridge_export_dialog_returns_tuple_with_path():
    """When the dialog returns a tuple, the bridge takes the first element."""
    bridge, statistics = _bridge_with_fake_capability(
        export_return={
            "filename": "report.csv",
            "activity_count": 1,
            "duration_seconds": 1800,
        },
    )
    bridge.set_window(_FakeDialogWindow(return_value=("output/report.csv",)))
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is True
    assert result["filename"] == "report.csv"


def test_bridge_export_dialog_raises_exception():
    """When the dialog raises, the bridge collapses to '导出失败' without leaking."""
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(
        _FakeDialogWindow(raise_exc=RuntimeError("Traceback SELECT C:\\secret"))
    )
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    lowered = str(result).lower()
    for token in SENSITIVE_TOKENS:
        assert token not in lowered
    assert statistics.export_statistics_csv_calls == []


# -- No window / dialog constant resolution --------------------------------


def test_bridge_export_no_window_returns_operation_failed():
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    # No set_window call -- bridge._window is None
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    assert statistics.export_statistics_csv_calls == []


def test_bridge_export_dialog_missing_file_dialog_constant(monkeypatch):
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    window = _FakeDialogWindow(return_value="unused.csv")
    bridge.set_window(window)

    class _BareWebview:
        pass

    monkeypatch.setitem(sys.modules, "webview", _BareWebview())
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    assert window.dialog_calls == 0
    assert statistics.export_statistics_csv_calls == []


def test_bridge_export_dialog_file_dialog_without_save_constant(monkeypatch):
    statistics = FakeStatisticsCapability()
    bridge = build_test_bridge(statistics=statistics)
    window = _FakeDialogWindow(return_value="unused.csv")
    bridge.set_window(window)

    class _FileDialogNoSave:
        pass

    class _WebviewNoSave:
        FileDialog = _FileDialogNoSave

    monkeypatch.setitem(sys.modules, "webview", _WebviewNoSave())
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    assert window.dialog_calls == 0


def test_bridge_export_dialog_uses_deprecated_save_dialog_fallback(monkeypatch):
    """When FileDialog.SAVE is missing but SAVE_DIALOG exists, the bridge uses it."""
    bridge, statistics = _bridge_with_fake_capability(
        export_return={
            "filename": "report.csv",
            "activity_count": 1,
            "duration_seconds": 1800,
        },
    )
    window = _FakeDialogWindow(return_value="output/report.csv")
    bridge.set_window(window)

    class _LegacyWebview:
        SAVE_DIALOG = 10

    monkeypatch.setitem(sys.modules, "webview", _LegacyWebview())
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is True
    assert result["filename"] == "report.csv"
    assert window.dialog_calls == 1


# -- Capability error code -> Chinese message mapping ----------------------


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("empty_data", "当前范围没有可导出的记录"),
        ("invalid_path", "请选择有效保存位置"),
        ("permission_denied", "导出失败，请检查保存位置和权限"),
        ("file_busy", "文件可能被占用，请关闭后重试"),
        ("storage_unavailable", "存储空间或设备不可用"),
        ("cleanup_failed", "导出未完成，临时文件清理失败"),
        ("stale_statistics_snapshot", "统计数据已更新，请重新加载后导出"),
        ("write_failed", "导出失败，请检查保存位置和权限"),
        ("operation_failed", "导出失败"),
        ("invalid_date", "请选择有效日期"),
        ("invalid_range", "请选择有效日期范围"),
        ("range_too_large", "日期范围过大"),
        ("invalid_project", "请选择有效项目"),
    ],
)
def test_bridge_export_capability_error_maps_to_chinese(code, message):
    statistics = FakeStatisticsCapability()
    statistics.export_statistics_csv_side_effect = StatisticsExportError(code)
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_FakeDialogWindow(return_value="output/x.csv"))
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is False
    assert result["error"] == message
    assert result["cancelled"] is False


def test_bridge_export_unknown_exception_collapses_to_chinese():
    statistics = FakeStatisticsCapability()
    statistics.export_statistics_csv_side_effect = RuntimeError(
        "Traceback SELECT FROM C:\\secret"
    )
    bridge = build_test_bridge(statistics=statistics)
    bridge.set_window(_FakeDialogWindow(return_value="output/report.csv"))
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is False
    assert result["error"] == "导出失败"
    lowered = str(result).lower()
    for token in SENSITIVE_TOKENS:
        assert token not in lowered


# -- Payload safety ----------------------------------------------------------


def test_bridge_export_success_payload_never_contains_full_path():
    """The success payload must only contain the basename, never the full path."""
    bridge, _ = _bridge_with_fake_capability(
        export_return={
            "filename": "report.csv",
            "activity_count": 1,
            "duration_seconds": 1800,
        },
    )
    bridge.set_window(
        _FakeDialogWindow(return_value="output/very/deep/nested/report.csv")
    )
    result = bridge.export_statistics_csv(
        "2026-06-25", "2026-06-25", VALID_TICKET
    )
    assert result["ok"] is True
    assert result["filename"] == "report.csv"
    lowered = str(result).lower()
    assert "output/very/deep/nested/report.csv" not in lowered
    assert "very" not in lowered
    assert "nested" not in lowered
    _assert_no_sensitive_keys(result)


def test_bridge_export_capability_called_with_correct_parameters():
    """The bridge must pass date_from, date_to, output_path, and ticket to the capability."""
    bridge, statistics = _bridge_with_fake_capability(
        export_return={
            "filename": "r.csv",
            "activity_count": 0,
            "duration_seconds": 0,
        },
    )
    bridge.set_window(_FakeDialogWindow(return_value="output/r.csv"))
    bridge.export_statistics_csv("2026-06-25", "2026-06-27", VALID_TICKET)
    assert len(statistics.export_statistics_csv_calls) == 1
    call = statistics.export_statistics_csv_calls[0]
    assert call[0] == "2026-06-25"
    assert call[1] == "2026-06-27"
    assert call[2] == "output/r.csv"
    assert call[3] == VALID_TICKET


def test_bridge_export_capability_called_with_project_id():
    """When project_id is provided, it is forwarded to the capability."""
    bridge, statistics = _bridge_with_fake_capability(
        export_return={
            "filename": "r.csv",
            "activity_count": 0,
            "duration_seconds": 0,
        },
    )
    bridge.set_window(_FakeDialogWindow(return_value="output/r.csv"))
    bridge.export_statistics_csv("2026-06-25", "2026-06-25", VALID_TICKET, "42")
    assert len(statistics.export_statistics_csv_calls) == 1
    call = statistics.export_statistics_csv_calls[0]
    assert call[4] == "42"


def test_bridge_export_strips_ticket_before_forwarding():
    """The bridge strips whitespace from the ticket before forwarding."""
    bridge, statistics = _bridge_with_fake_capability(
        export_return={
            "filename": "r.csv",
            "activity_count": 0,
            "duration_seconds": 0,
        },
    )
    bridge.set_window(_FakeDialogWindow(return_value="output/r.csv"))
    bridge.export_statistics_csv("2026-06-25", "2026-06-25", "  valid-ticket  ")
    call = statistics.export_statistics_csv_calls[0]
    assert call[3] == "valid-ticket"


# -- Summary remains read-only ----------------------------------------------


def test_bridge_get_statistics_export_summary_remains_read_only():
    """The summary method must not open a dialog or write a file."""
    statistics = FakeStatisticsCapability()
    statistics.get_statistics_export_view_model_return = {
        "summary": {"date_from": "2026-06-25"},
        "export_ticket": {"ticket_revision": "abc"},
    }
    bridge = build_test_bridge(statistics=statistics)
    window = _FakeDialogWindow(return_value="should_not_be_used.csv")
    bridge.set_window(window)
    result = bridge.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert result["ok"] is True
    assert window.dialog_calls == 0
    assert statistics.export_statistics_csv_calls == []


# -- set_window does not start GUI ------------------------------------------


def test_bridge_set_window_does_not_start_gui():
    bridge = build_test_bridge()
    assert bridge._window is None
    bridge.set_window(object())
    assert bridge._window is not None


# -- Error message table stability ------------------------------------------


def test_bridge_export_error_messages_are_stable_chinese():
    from worktrace.webview_ui.bridge_statistics import (
        _STATISTICS_EXPORT_ERROR_MESSAGES,
    )

    expected = {
        "invalid_date": "请选择有效日期",
        "invalid_range": "请选择有效日期范围",
        "range_too_large": "日期范围过大",
        "invalid_project": "请选择有效项目",
        "empty_data": "当前范围没有可导出的记录",
        "invalid_path": "请选择有效保存位置",
        "permission_denied": "导出失败，请检查保存位置和权限",
        "file_busy": "文件可能被占用，请关闭后重试",
        "storage_unavailable": "存储空间或设备不可用",
        "cleanup_failed": "导出未完成，临时文件清理失败",
        "stale_statistics_snapshot": "统计数据已更新，请重新加载后导出",
        "write_failed": "导出失败，请检查保存位置和权限",
        "operation_failed": "导出失败",
    }
    for code, message in expected.items():
        assert _STATISTICS_EXPORT_ERROR_MESSAGES.get(code) == message


# -- Import boundary --------------------------------------------------------


def test_bridge_export_does_not_import_backend_internals():
    import worktrace

    bridge_dir = Path(worktrace.__file__).parent / "webview_ui"
    for name in (
        "bridge.py",
        "bridge_common.py",
        "bridge_dialogs.py",
        "bridge_overview.py",
        "bridge_settings.py",
        "bridge_statistics.py",
        "bridge_timeline.py",
        "bridge_rules.py",
    ):
        source = (bridge_dir / name).read_text(encoding="utf-8")
        for forbidden in (
            "from ..services",
            "from worktrace.services",
            "from ..db",
            "from worktrace.db",
            "from ..collector",
            "from worktrace.collector",
            "from ..security",
            "from worktrace.security",
            "from ..runtime",
            "from worktrace.runtime",
            "from ..config",
            "from worktrace.config",
            "import worktrace.services",
            "import worktrace.db",
            "import worktrace.collector",
            "import worktrace.security",
            "import worktrace.runtime",
            "import worktrace.config",
        ):
            assert forbidden not in source
