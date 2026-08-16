from __future__ import annotations

import json

import pytest

from worktrace.integrations.fd_work.main_window_sink import FDWorkMainWindowSink


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _LoadedEvent:
    def __init__(self, loaded: bool = False) -> None:
        self.loaded = loaded

    def is_set(self) -> bool:
        return self.loaded


class _Events:
    def __init__(self, *, loaded: bool = False) -> None:
        self.loaded = _LoadedEvent(loaded)


class _Window:
    def __init__(self, *, fail: bool = False, loaded: bool = False) -> None:
        self.fail = fail
        self.events = _Events(loaded=loaded)
        self.scripts: list[str] = []

    def evaluate_js(self, script: str) -> None:
        if self.fail:
            raise RuntimeError("closed")
        self.scripts.append(script)


def test_typed_sink_waits_for_main_webview_load_even_after_renderer_ready() -> None:
    sink = FDWorkMainWindowSink()
    window = _Window()
    payload = {"enabled": True, "message": "quoted ' value"}

    sink.bind_window(window)
    sink.status_changed(payload)
    sink.mark_ready()
    sink.status_changed(payload)
    sink.picker_result({"ok": True, "request_id": "r1"})

    assert window.scripts == []

    window.events.loaded.loaded = True
    sink.status_changed(payload)
    sink.picker_result({"ok": True, "request_id": "r1"})

    assert window.scripts == [
        "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkStatus("
        + json.dumps(payload, ensure_ascii=True)
        + ")",
        "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkCasePickerResult("
        + json.dumps({"ok": True, "request_id": "r1"}, ensure_ascii=True)
        + ")",
    ]


def test_typed_sink_fails_closed_without_main_window_loaded_event() -> None:
    sink = FDWorkMainWindowSink()

    class _BareWindow:
        def __init__(self) -> None:
            self.scripts: list[str] = []

        def evaluate_js(self, script: str) -> None:
            self.scripts.append(script)

    window = _BareWindow()
    sink.bind_window(window)
    sink.mark_ready()
    sink.status_changed({"enabled": True})
    sink.picker_result({"ok": False, "error": "picker_canceled"})

    assert window.scripts == []


def test_typed_sink_drops_closed_window_delivery_fail_soft() -> None:
    sink = FDWorkMainWindowSink()
    sink.bind_window(_Window(fail=True, loaded=True))
    sink.mark_ready()

    sink.status_changed({"enabled": True})
    sink.picker_result({"ok": False, "error": "picker_canceled"})
    sink.mark_unavailable()
    sink.status_changed({"enabled": False})
