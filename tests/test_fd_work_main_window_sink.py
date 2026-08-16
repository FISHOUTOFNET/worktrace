from __future__ import annotations

import json
import threading

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


class _BlockingFirstWindow(_Window):
    def __init__(self) -> None:
        super().__init__(loaded=True)
        self.first_started = threading.Event()
        self.release_first = threading.Event()
        self.second_started = threading.Event()
        self._call_lock = threading.Lock()
        self._call_count = 0

    def evaluate_js(self, script: str) -> None:
        with self._call_lock:
            self._call_count += 1
            call_number = self._call_count
            self.scripts.append(script)
        if call_number == 1:
            self.first_started.set()
            self.release_first.wait(timeout=2.0)
        elif call_number == 2:
            self.second_started.set()


class _RecordingWindow(_Window):
    def __init__(self) -> None:
        super().__init__(loaded=True)
        self.received = threading.Event()

    def evaluate_js(self, script: str) -> None:
        self.scripts.append(script)
        self.received.set()


def _status_script(payload: dict[str, object]) -> str:
    return (
        "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkStatus("
        + json.dumps(payload, ensure_ascii=True)
        + ")"
    )


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
        _status_script(payload),
        "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkCasePickerResult("
        + json.dumps({"ok": True, "request_id": "r1"}, ensure_ascii=True)
        + ")",
    ]


def test_typed_sink_fails_closed_without_usable_loaded_signal() -> None:
    sink = FDWorkMainWindowSink()
    window = _Window()
    window.events.loaded = object()
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


def test_async_sink_does_not_block_lifecycle_caller_on_evaluate_js() -> None:
    sink = FDWorkMainWindowSink(deliver_asynchronously=True)
    window = _BlockingFirstWindow()
    returned = threading.Event()
    sink.bind_window(window)
    sink.mark_ready()

    caller = threading.Thread(
        target=lambda: (sink.status_changed({"sequence": 1}), returned.set()),
        daemon=True,
    )
    caller.start()
    try:
        assert window.first_started.wait(timeout=1.0)
        assert returned.wait(timeout=0.2)
    finally:
        window.release_first.set()
        caller.join(timeout=1.0)


def test_async_sink_serializes_delivery_fifo() -> None:
    sink = FDWorkMainWindowSink(deliver_asynchronously=True)
    window = _BlockingFirstWindow()
    first = {"sequence": 1}
    second = {"sequence": 2}
    sink.bind_window(window)
    sink.mark_ready()

    sink.status_changed(first)
    assert window.first_started.wait(timeout=1.0)

    sink.status_changed(second)
    assert not window.second_started.wait(timeout=0.1)

    window.release_first.set()
    assert window.second_started.wait(timeout=1.0)
    assert window.scripts == [_status_script(first), _status_script(second)]


def test_async_sink_drops_stale_queue_entries_after_window_rebind() -> None:
    sink = FDWorkMainWindowSink(deliver_asynchronously=True)
    old_window = _BlockingFirstWindow()
    new_window = _RecordingWindow()
    first = {"sequence": 1}
    stale = {"sequence": 2}
    current = {"sequence": 3}
    sink.bind_window(old_window)
    sink.mark_ready()

    sink.status_changed(first)
    assert old_window.first_started.wait(timeout=1.0)
    sink.status_changed(stale)

    sink.mark_unavailable()
    sink.bind_window(new_window)
    sink.mark_ready()
    sink.status_changed(current)

    old_window.release_first.set()
    assert new_window.received.wait(timeout=1.0)
    assert old_window.scripts == [_status_script(first)]
    assert new_window.scripts == [_status_script(current)]
