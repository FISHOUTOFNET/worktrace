import json
import time

from worktrace.services import settings_service, statistics_service
from worktrace.services.live_time_service import snapshot_signature
from worktrace.ui.overview_view import OverviewView, _snapshot_signature, current_activity_text


class FakeLabel:
    def __init__(self):
        self.config = {}

    def configure(self, **kwargs):
        self.config.update(kwargs)

    def cget(self, key):
        return self.config.get(key, "")


class FakeRow:
    def __init__(self):
        self.grid_calls = []
        self.destroyed = False

    def grid(self, *args, **kwargs):
        self.grid_calls.append((args, kwargs))

    def destroy(self):
        self.destroyed = True


def test_overview_current_activity_text_uses_snapshot_duration(temp_db):
    settings_service.set_setting(
        "current_activity_snapshot",
        json.dumps(
            {
                "resource_display_name": "Spec.docx",
                "app_name": "Word",
                "process_name": "word.exe",
                "inferred_project_name": "Client",
                "status": "normal",
                "start_time": "",
                "elapsed_seconds": 65,
                "is_persisted": True,
            },
            ensure_ascii=False,
        ),
    )

    assert current_activity_text() == "当前活动：Spec.docx｜Client｜00:01:05｜已进入历史"


def test_overview_current_activity_text_handles_missing_snapshot(temp_db):
    assert current_activity_text() == "当前活动：无"


def test_overview_open_timeline_passes_filter_and_session_context():
    calls = []
    view = object.__new__(OverviewView)
    view.open_timeline_callback = lambda **kwargs: calls.append(kwargs)

    OverviewView._open_timeline(view, True, session_id="1-2", target_date="2026-06-18")

    assert calls == [
        {
            "only_uncategorized": True,
            "session_id": "1-2",
            "target_date": "2026-06-18",
        }
    ]


def test_overview_same_current_activity_ticks_without_full_refresh(temp_db):
    snapshot = {
        "resource_display_name": "Spec.docx",
        "inferred_project_name": "Client",
        "status": "normal",
        "start_time": "2026-06-18 09:00:00",
        "is_persisted": True,
    }
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False))
    view = object.__new__(OverviewView)
    view._current_snapshot = snapshot
    view._current_signature = _snapshot_signature(snapshot)
    view._last_data_refresh_monotonic = time.monotonic()
    view.current_activity_label = FakeLabel()
    refresh_calls = []
    view.refresh = lambda: refresh_calls.append("refresh")

    OverviewView.refresh_current_activity(view)

    assert refresh_calls == []
    assert view.current_activity_label.config["text"].startswith("当前活动：Spec.docx｜Client｜")


def test_overview_live_tick_updates_kpis_without_statistics_query(temp_db, monkeypatch):
    snapshot = {
        "resource_display_name": "Spec.docx",
        "inferred_project_name": "Client",
        "status": "normal",
        "start_time": "",
        "elapsed_seconds": 35,
        "is_persisted": True,
        "persisted_activity_id": 1,
    }
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False))
    view = object.__new__(OverviewView)
    view._current_snapshot = snapshot
    view._current_signature = snapshot_signature(snapshot)
    view._last_data_refresh_monotonic = time.monotonic()
    view._last_scope_range = ("2026-06-18", "2026-06-18")
    view._kpi_base_values = {"total": 30, "classified": 30, "uncategorized": 0}
    view._kpi_base_live_seconds = 30
    view.kpi_value_labels = {"total": FakeLabel(), "classified": FakeLabel(), "uncategorized": FakeLabel()}
    view.current_activity_label = FakeLabel()
    view._recent_rows = {}
    view.scope_var = type("Scope", (), {"get": lambda _self: "今日概览"})()
    view._scope_dates = lambda: ("2026-06-18", "2026-06-18")
    view.refresh = lambda: (_ for _ in ()).throw(AssertionError("full refresh should not run"))

    monkeypatch.setattr(statistics_service, "get_summary", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("statistics query should not run")))
    monkeypatch.setattr("worktrace.ui.overview_view.snapshot_seconds_for_date_range", lambda *_args, **_kwargs: 35)

    OverviewView.refresh_current_activity(view)

    assert view.kpi_value_labels["total"].config["text"] == "00:00:35"
    assert view.kpi_value_labels["classified"].config["text"] == "00:00:35"


def test_overview_recent_project_title_includes_description():
    view = object.__new__(OverviewView)
    view._recent_rows = {}
    view._recent_empty = None
    view._hide_recent_empty = lambda: None
    view._show_recent_empty = lambda: None
    view._sessions_for_range = lambda *_args, **_kwargs: [
        {
            "session_id": "1-1",
            "project_name": "Client",
            "project_description": "billable",
            "start_time": "2026-06-18 09:00:00",
            "end_time": "2026-06-18 09:10:00",
            "status_summary": "Spec.docx",
            "duration_seconds": 600,
            "report_date": "2026-06-18",
        }
    ]

    def create_row(session_id):
        return {
            "row": FakeRow(),
            "time": FakeLabel(),
            "title": FakeLabel(),
            "subtitle": FakeLabel(),
            "duration": FakeLabel(),
            "session_id": session_id,
            "target_date": "2026-06-18",
        }

    view._create_recent_row = create_row

    OverviewView._refresh_recent_sessions(view, "2026-06-18", "2026-06-18")

    assert view._recent_rows["1-1"]["title"].config["text"] == "Client (billable)"
