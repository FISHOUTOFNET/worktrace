from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def _resource(name: str) -> str:
    return (ROOT / "worktrace" / "webview_ui" / name).read_text(encoding="utf-8")


def _source(name: str) -> str:
    return (ROOT / "worktrace" / "webview_ui" / "js" / name).read_text(encoding="utf-8")


def _func_body(source: str, name: str) -> str:
    start = source.find("function " + name)
    assert start != -1
    end = source.find("\n    function ", start + 1)
    return source[start:end] if end != -1 else source[start:]


def test_timeline_time_points_use_minute_precision_with_separate_width_semantics():
    timeline = _source("timeline.js")
    body = _func_body(timeline, "formatTimelineStartTime")
    css = _resource("ui_components.css")

    assert "slice(11, 19)" in body
    assert "return exact.slice(0, 5);" in body
    assert "--record-start-time-width" in css
    item = re.search(r"\.timeline-item\s*\{([^}]*)\}", css)
    assert item is not None
    assert "var(--record-start-time-width)" in item.group(1)
    assert "var(--record-duration-width)" in item.group(1)


def test_project_rules_keep_card_height_and_rule_typography_visually_stable():
    render = _source("rules_render.js")
    body = _func_body(render, "renderProjectRuleProject")
    css = _resource("ui_components.css")

    assert 'rules-project-description is-empty' in body
    assert 'text("暂无描述", "暂无描述")' in body
    assert ".rules-project-title-group:not(:has(.rules-project-description))::after" not in css

    rule_row = re.search(r"\.rules-row\s*\{([^}]*)\}", css)
    assert rule_row is not None and "var(--font-size-md)" in rule_row.group(1)
    assert re.search(
        r"\.rules-kind-badge,\s*\.rules-detail\s*\{[^}]*font-size:\s*inherit",
        css,
    )


def test_settings_and_project_editor_use_explicit_consistent_layout_rules():
    css = _resource("ui_components.css")

    setting_small = re.search(r"\.setting-row small\s*\{([^}]*)\}", css)
    assert setting_small is not None
    assert "var(--font-size-sm)" in setting_small.group(1)
    assert (
        "#rules-panel-project-section:not(:has(#rules-panel-fd-work-picker:not([hidden])))"
        in css
    )
    assert "grid-column: 1 / -1" in css


def test_statistics_and_timeline_autocomplete_keep_stable_visual_bounds():
    css = _resource("ui_components.css")

    desktop = re.search(r"@media \(min-width: 960px\)\s*\{(.*)\}\s*$", css, re.DOTALL)
    assert desktop is not None
    assert re.search(r"\.statistics-date-range\s*\{[^}]*min-width:", desktop.group(1))
    shell = re.search(r"\.statistics-date-control-shell\s*\{([^}]*)\}", css)
    assert shell is not None
    assert "width: var(--date-control-width)" in shell.group(1)
    assert "min-width: var(--date-control-width)" in shell.group(1)
    assert ".statistics-date-empty-label" in css

    menu = re.search(r"\.timeline-edit-panel \.project-autocomplete-menu\s*\{([^}]*)\}", css)
    assert menu is not None
    assert "width: 100%" in menu.group(1)
    assert "max-width: 100%" in menu.group(1)

    metric = re.search(r"\.metric-strip\s*\{([^}]*)\}", css)
    assert metric is not None
    assert "border-width: 0" in metric.group(1)
    assert "repeat(5, minmax(0, 1fr))" in metric.group(1)
