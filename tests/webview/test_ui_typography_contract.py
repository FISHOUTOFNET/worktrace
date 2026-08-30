"""Cross-page typography and date-control presentation contracts."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

WEBVIEW_UI_DIR = Path(__file__).resolve().parents[2] / "worktrace" / "webview_ui"


def _read(name: str) -> str:
    return (WEBVIEW_UI_DIR / name).read_text(encoding="utf-8")


def _block(source: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match is not None, selector
    return match.group(1)


def test_overview_time_typography_uses_shared_size_tokens() -> None:
    styles = _read("styles.css")
    overview = _block(styles, ".overview-page")
    assert "--overview-record-time-size: 13px;" in overview

    primary_times = re.search(
        r"\.overview-page \.page-total strong,\s*"
        r"\.overview-page \.current-duration\s*\{([^}]*)\}",
        styles,
    )
    assert primary_times is not None
    assert "font-size: var(--font-size-xl);" in primary_times.group(1)
    assert "font-size: var(--font-size-2xl);" not in primary_times.group(1)

    recent_duration = _block(styles, ".recent-duration")
    timeline_duration = _block(styles, ".timeline-item-duration")
    assert "font-size: var(--overview-record-time-size);" in recent_duration
    assert "font-size: 13px;" in timeline_duration


def test_retired_statistics_all_time_label_css_is_removed() -> None:
    styles = _read("styles.css")
    assert ".statistics-all-time-label" not in styles


def test_toolbar_labels_share_primary_control_text_layer() -> None:
    styles = _read("styles.css")
    toolbar_label = _block(styles, ".toolbar label")
    field_label = _block(styles, ".field > span")

    assert "color: var(--color-text);" in toolbar_label
    assert "var(--color-text-secondary)" not in toolbar_label
    assert "color: var(--color-text-secondary);" in field_label
    assert "font-size: var(--font-size-sm);" in field_label


def test_statistics_empty_date_copy_inherits_native_control_typography() -> None:
    final = _read("ui_components.css")
    shell = _block(final, ".statistics-date-control-shell")
    native = _block(final, ".statistics-date-control-shell .date-control")
    empty = _block(final, ".statistics-date-empty-label")

    assert "font: var(--font-size-md)/var(--line-height-normal) var(--font-sans);" in shell
    assert "font-weight: 400;" in shell
    assert "font: inherit;" in native
    assert "font: inherit;" in empty
    assert "line-height: 1;" not in empty


def test_stylesheet_revision_keys_are_bumped_for_typography_change() -> None:
    index = _read("index_fd_work_v5.html")
    stale_revisions = {
        "styles.css": "318288756e2856fc",
        "ui_components.css": "0e010ece98a374fa",
    }
    for name, stale_revision in stale_revisions.items():
        match = re.search(re.escape(name) + r"\?v=([0-9a-f]{16})", index)
        assert match is not None
        assert match.group(1) != stale_revision
