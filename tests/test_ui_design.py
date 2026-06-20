import inspect

from worktrace.ui import design
from worktrace.ui.statistics_view import StatisticsView
from worktrace.ui.timeline_view import TimelineView
from worktrace.ui.overview_view import OverviewView
from worktrace.ui.project_rules_view import ProjectRulesView


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


def test_timeline_project_table_uses_project_heading_and_wider_time_column():
    source = inspect.getsource(TimelineView._build_session_table)

    assert '"project": "项目"' in source
    assert '"项目/状态"' not in source
    assert '"time": 132' in source
    assert "checkbox_width=16" in source
    assert "checkbox_height=16" in source


def test_statistics_rows_keep_fixed_bar_track_columns():
    source = inspect.getsource(StatisticsView._create_project_stat_row)

    assert "minsize=230" in source
    assert "minsize=94" in source
    assert 'width=220' in source
    assert 'width=90' in source


def test_overview_recent_rows_use_primary_text_and_week_time_break():
    row_source = inspect.getsource(OverviewView._create_recent_row)
    time_source = inspect.getsource(__import__("worktrace.ui.overview_view", fromlist=["_session_time"])._session_time)

    assert "text_color=design.TEXT" in row_source
    assert 'return f"{start[5:10]}\\n{time_range}"' in time_source


def test_project_rule_project_actions_use_short_labels():
    source = inspect.getsource(ProjectRulesView._project_group)

    assert '"禁用项目"' not in source
    assert '"删除项目"' not in source
    assert '"禁用" if project_enabled else "启用"' in source
    assert 'text="删除"' in source
