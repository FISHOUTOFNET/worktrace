from __future__ import annotations

import json

import pytest

from tests.support.collector_stream import CollectorStream
from worktrace.services import settings_service, timeline_service
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.db,
    pytest.mark.live_display,
    pytest.mark.collector_runtime,
]


@pytest.fixture()
def stream(temp_db, monkeypatch) -> CollectorStream:
    monkeypatch.setattr(
        timeline_service,
        "get_default_report_date",
        lambda: "2026-06-18",
    )
    return CollectorStream()


def _actions(stream: CollectorStream) -> list[str]:
    return [t.short_activity_action for t in stream.trace.traces if t.short_activity_action]


def test_stream_short_activity_absorbs_and_resumes_with_trace(stream):
    stream.start("A", at=0).same("A", at=60).switch("B", at=120).switch("A", at=140)

    rows = stream.rows()
    assert len(rows) == 1
    assert rows[0]["window_title"] == "A"
    assert rows[0]["end_time"] is None
    assert rows[0]["duration_seconds"] == 140
    assert "merge_to_anchor" in _actions(stream)
    assert "resume_anchor" in _actions(stream)
    assert stream.snapshot()["persisted_activity_id"] == rows[0]["id"]


def test_stream_b_at_30s_persists_independently_and_updates_display(stream):
    stream.start("A", at=0).same("A", at=60).switch("B", at=120).same("B", at=150)

    rows = sorted(stream.rows(), key=lambda row: row["start_time"])
    assert [r["window_title"] for r in rows] == ["A", "B"]
    assert rows[0]["end_time"] is not None
    assert rows[1]["end_time"] is None

    overview = WebViewBridge().get_overview()
    assert overview["live_clock"]["live_state"] == "persisted_open"
    live_rows = [
        row for row in overview["activities"]
        if row.get("live_state") == "persisted_open"
    ]
    assert live_rows, "Overview must overlay the persisted-open B row"
    assert rows[1]["id"] in live_rows[0]["activity_ids"]
    assert live_rows[0]["open_activity_id"] == rows[1]["id"]
    assert any(t.snapshot_action == "persisted_open" for t in stream.trace.traces)


def test_stream_pause_boundary_blocks_later_short_absorption(stream):
    stream.start("A", at=0).same("A", at=60).pause(at=120)
    stream.resume("B", at=180).switch("C", at=200)

    rows = [r for r in stream.rows() if r["window_title"] in {"A", "B", "C"}]
    assert [r["window_title"] for r in rows] == ["A"]
    assert rows[0]["duration_seconds"] == 120
    assert "drop" in _actions(stream)
    assert any(t.short_activity_reason == "no_legal_anchor" for t in stream.trace.traces)


def test_decision_trace_is_privacy_safe(stream):
    sensitive_title = "Sensitive Window Title 7Q2"
    sensitive_path = "C:\\Users\\Alice\\Secret\\plan.docx"
    settings_service.set_setting(
        "current_activity_snapshot",
        json.dumps(
            {
                "window_title": sensitive_title,
                "file_path_hint": sensitive_path,
                "clipboard": "copied secret",
            }
        ),
    )
    stream.start(sensitive_title, at=0).same(sensitive_title, at=30).stop(at=40)

    serialized = json.dumps(
        [trace.to_dict() for trace in stream.trace.traces],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert sensitive_title not in serialized
    assert sensitive_path not in serialized
    assert "copied secret" not in serialized
    assert "SELECT " not in serialized
    assert "Traceback" not in serialized
    assert any(trace.incoming_signature_hash for trace in stream.trace.traces)
