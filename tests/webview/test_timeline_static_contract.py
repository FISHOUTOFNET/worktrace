from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(name: str) -> str:
    return (ROOT / "worktrace" / "webview_ui" / "js" / name).read_text(encoding="utf-8")


def test_timeline_consumes_canonical_entries_and_authoritative_mutation_result():
    source = _source("timeline.js")
    assert "data.entries" in source
    assert "selection_hint" in source
    assert "snapshot_revision" in source
    assert "outcome_type" in source
    assert "data.sessions" not in source
    assert "session_id" not in source


def test_details_and_mutation_have_single_owner_models():
    source = _source("timeline.js") + _source("core.js")
    assert "detailsOwner" in source
    assert "detailsRequestToken" not in source
    assert "selectedSessionId" not in source
    assert "selectedSessionLiveKey" not in source


def test_unknown_and_refresh_failure_messages_are_explicit():
    source = _source("timeline.js")
    assert "操作结果尚未确认，可重试同一操作或刷新核对" in source
    assert "操作已保存，但刷新失败" in source


def test_timeline_empty_state_uses_shared_visual_language():
    source = _source("timeline.js")
    assert 'class="empty-state timeline-empty"' in source
    assert "当日暂无时间记录" in source
    assert "选择其他日期，或开始记录新的工作活动。" in source
