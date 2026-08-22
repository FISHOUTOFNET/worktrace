from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"


def _resource(name: str) -> str:
    return (UI_ROOT / name).read_text(encoding="utf-8")


def test_page_loading_indicators_are_owned_by_their_content_regions():
    html = _resource("index_fd_work_v5.html")

    timeline = html[html.index('id="page-timeline"') : html.index('id="page-statistics"')]
    assert timeline.index('class="timeline-workspace"') < timeline.index('id="timeline-loading"')
    assert timeline.index('id="timeline-loading"') < timeline.index('id="timeline-sessions-list"')
    assert 'id="timeline-loading" class="content-loading-overlay"' in timeline
    assert 'class="skeleton"' not in timeline

    rules = html[html.index('id="page-rules"') : html.index('id="page-settings"')]
    assert rules.index('class="rules-scroll-region"') < rules.index('id="rules-loading"')
    assert rules.index('id="rules-loading"') < rules.index('id="rules-list"')
    assert 'id="rules-loading" class="content-loading-overlay"' in rules
    assert 'class="skeleton"' not in rules


def test_content_loading_overlay_does_not_participate_in_normal_layout():
    css = _resource("loading_presentation.css")
    overlay = re.search(r"\.content-loading-overlay\s*\{([^}]*)\}", css)
    rules_region = re.search(r"\.rules-scroll-region\s*\{([^}]*)\}", css)

    assert overlay is not None
    assert "position: absolute" in overlay.group(1)
    assert "inset: 0" in overlay.group(1)
    assert "display: grid" in overlay.group(1)
    assert "pointer-events: none" in overlay.group(1)

    assert rules_region is not None
    assert "position: relative" in rules_region.group(1)
