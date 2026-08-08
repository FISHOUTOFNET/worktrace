from __future__ import annotations

import json

import pytest

from worktrace.integrations.fd_work.main_window_sink import FDWorkMainWindowSink


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Window:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.scripts = []

    def evaluate_js(self, script):
        if self.fail:
            raise RuntimeError("closed")
        self.scripts.append(script)


def test_typed_sink_serializes_payloads_and_honors_renderer_readiness():
    sink = FDWorkMainWindowSink()
    window = _Window()
    payload = {"enabled": True, "message": "quoted ' value"}

    sink.bind_window(window)
    sink.status_changed(payload)
    assert window.scripts == []

    sink.mark_ready()
    sink.status_changed(payload)

    assert window.scripts == [
        "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkStatus("
        + json.dumps(payload, ensure_ascii=True)
        + ")"
    ]


def test_typed_sink_drops_stale_or_closed_window_delivery_fail_soft():
    sink = FDWorkMainWindowSink()
    sink.bind_window(_Window(fail=True))
    sink.picker_result({"ok": False, "error": "picker_canceled"})
    sink.mark_unavailable()
    sink.status_changed({"enabled": False})
