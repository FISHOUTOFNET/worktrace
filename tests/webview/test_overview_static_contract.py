from __future__ import annotations
import os, sys
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from static_helpers import func_body, read_js, read_resource  # noqa: E402


def test_overview_renders_authoritative_groups_and_timeline_intents():
    source = read_js("overview.js")
    show = func_body(source, "showOverview")
    assert "bundle.current_activity" in show
    assert "bundle.current_session" in show
    assert "renderAttention(bundle.attention" in show
    assert "renderRecent(bundle.recent)" in show
    intent = func_body(source, "timelineIntent")
    assert "projection_instance_key" in intent
    assert "focusTarget" in intent
    assert 'App.switchPage("timeline")' in intent


def test_derived_description_has_explicit_non_color_label():
    source = read_js("overview.js")
    assert 'description_source === "derived"' in source
    assert 'content: "自动摘要"' in read_resource("styles.css")


def test_overview_summary_reads_the_accepted_overview_payload_directly():
    show = func_body(read_js("overview.js"), "showOverview")
    assert "bundle.project_count" in show
    assert "bundle.classified_duration" in show
    assert "bundle.uncategorized_duration" in show
    assert "bundle.overview" not in show


def test_overview_shipping_ui_uses_authoritative_module_names():
    """Regression guard: the shipping UI must use the canonical module
    names "当前活动 / 最近记录 / 待整理" and must not reintroduce the
    retired "最近活动" label in user-visible markup or ARIA."""
    html = read_resource("index.html")
    assert "当前活动" in html
    assert "最近记录" in html
    assert "待整理" in html
    assert "最近活动" not in html, "shipping HTML must not use retired '最近活动' label"
    overview_js = read_js("overview.js")
    assert "暂无最近记录" in overview_js, "empty state must use '暂无最近记录'"
    assert "最近活动" not in overview_js, "overview.js must not use retired '最近活动' label"


def test_overview_view_model_does_not_reintroduce_disjoint_filter():
    """Regression guard: the Overview ViewModel must not rebuild the
    disjoint `recent_visible` filter that excluded current and attention
    rows from recent. Attention is a subset of recent, not a disjoint
    partition."""
    import inspect
    from worktrace.services import view_model_service

    source = inspect.getsource(view_model_service)
    assert "recent_visible" not in source, (
        "view_model_service must not reintroduce the retired 'recent_visible' disjoint filter"
    )
    assert "attention_keys" not in source, (
        "view_model_service must not rebuild the 'attention_keys' disjoint exclusion set"
    )


def test_current_activity_card_uses_structured_dto_not_display_string():
    """Regression guard: the Overview current-activity card must read the
    structured DTO fields (resource_name, app_name, project_name) and must
    not parse the combined `display` string or use current_session as the
    card content source. The unstructured Timeline path may still use
    `current.display` as transport, so the guard isolates the structured
    block via a comment marker."""
    core_js = read_js("core.js")
    marker = "// Structured Overview card"
    idx = core_js.find(marker)
    assert idx != -1, "core.js must delimit the structured Overview card path"
    structured_block = core_js[idx:]
    assert "current.resource_name" in structured_block
    assert "current-context" in structured_block or "currentContextLine" in structured_block
    assert 'split("｜")' not in structured_block, (
        "structured Overview card must not parse the combined display string"
    )
    assert "current_session.project_name" not in structured_block, (
        "structured Overview card must not read current_session for card content"
    )
