from __future__ import annotations
import os, sys
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from static_helpers import func_body, read_js, read_resource  # noqa: E402


def test_overview_renders_authoritative_deduplicated_groups_and_timeline_intents():
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
