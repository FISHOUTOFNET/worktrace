import inspect

from worktrace.ui import design
from worktrace.ui.statistics_view import StatisticsView
from worktrace.ui.timeline_view import TimelineView


def test_range_controls_use_previous_current_today_order():
    statistics_source = inspect.getsource(StatisticsView._build)
    timeline_source = inspect.getsource(TimelineView._build)

    assert 'values=["上周", "本周", "今日"]' in statistics_source
    assert 'values=["上周", "本周", "今日"]' in timeline_source


def test_statistics_view_no_longer_builds_markdown_button():
    assert "Markdown" not in inspect.getsource(StatisticsView._build)


def test_design_uses_gray_accent_instead_of_blue_buttons():
    old_blue_values = {"#2563eb", "#60a5fa", "#1d4ed8", "#3b82f6", "#dbeafe", "#1e3a8a"}

    assert design.ACCENT[0] not in old_blue_values
    assert design.ACCENT[1] not in old_blue_values
    assert design.ACCENT_SOFT[0] not in old_blue_values
    assert design.ACCENT_SOFT[1] not in old_blue_values
    assert 'kwargs.setdefault("text_color", TEXT)' in inspect.getsource(design.segmented_button)
