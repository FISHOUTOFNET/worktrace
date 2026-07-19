from __future__ import annotations
from tests.support import runtime_state_fixture

import json

import pytest

from tests.support.collector_stream import CollectorStream
from worktrace.services import settings_service, timeline_service
from worktrace.webview_ui.bridge import WebViewBridge


pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.live_display, pytest.mark.collector_runtime]


@pytest.fixture()
def stream(temp_db, monkeypatch) -> CollectorStream:
    monkeypatch.setattr(timeline_service, "get_default_report_date", lambda: "2026-06-18")
    return CollectorStream()


def test_stream_switches_close_and_open_their_own_rows(stream):
    stream.start("A", at=0).same("A", at=60).switch("B", at=120).switch("A", at=140)
    rows = sorted(stream.rows(), key=lambda row: row["start_time"])
    assert [row["window_title"] for row in rows] == ["A", "B", "A"]
    assert [row["duration_seconds"] for row in rows] == [120, 20, 0]
    assert rows[-1]["end_time"] is None
    assert stream.snapshot()["persisted_activity_id"] == rows[-1]["id"]


def test_stream_open_row_is_the_only_live_display_target(stream):
    stream.start("A", at=0).same("A", at=60).switch("B", at=120)
    row = stream.rows()[-1]
    overview = WebViewBridge().get_overview()
    assert overview["runtime"]["clock"]["live_state"] == "persisted_open"
    live_rows = [item for item in overview["activities"] if item.get("live_state") == "persisted_open"]
    assert live_rows and row["id"] in live_rows[0]["activity_ids"]


def test_decision_trace_is_privacy_safe(stream):
    sensitive_title = "Sensitive Window Title 7Q2"
    sensitive_path = "C:\\Users\\Alice\\Secret\\plan.docx"
    runtime_state_fixture.set_setting("current_activity_snapshot", json.dumps({"window_title": sensitive_title, "file_path_hint": sensitive_path, "clipboard": "copied secret"}))
    stream.start(sensitive_title, at=0).same(sensitive_title, at=30).stop(at=40)
    serialized = json.dumps([trace.to_dict() for trace in stream.trace.traces], ensure_ascii=False, sort_keys=True)
    for secret in (sensitive_title, sensitive_path, "copied secret", "SELECT ", "Traceback"):
        assert secret not in serialized
