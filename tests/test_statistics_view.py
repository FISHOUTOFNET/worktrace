import json

from worktrace.services import settings_service, statistics_service
from worktrace.services.live_time_service import snapshot_signature
from worktrace.ui.statistics_view import StatisticsView


class FakeLabel:
    def __init__(self):
        self.config = {}

    def configure(self, **kwargs):
        self.config.update(kwargs)


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_statistics_live_tick_updates_from_cache_without_statistics_query(temp_db, monkeypatch):
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
    view = object.__new__(StatisticsView)
    view.start_var = FakeVar("2026-06-18")
    view.end_var = FakeVar("2026-06-18")
    view._default_report_date = "2026-06-18"
    view._summary_labels = {key: FakeLabel() for key in ["total", "effective", "idle", "excluded", "uncategorized"]}
    view._base_summary_values = {"total": 30, "effective": 30, "idle": 0, "excluded": 0, "uncategorized": 0}
    view._base_project_rows = [{"project": "Client", "total_duration": 30, "record_count": 1}]
    view._base_live_seconds = 30
    view._current_snapshot = snapshot
    view._current_signature = snapshot_signature(snapshot)
    view._sync_range_buttons = lambda: None
    view._dates_are_valid = lambda *args, **kwargs: True
    synced = []
    view._sync_project_rows = lambda rows, total: synced.append((rows, total))

    monkeypatch.setattr(statistics_service, "get_summary", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("statistics query should not run")))
    monkeypatch.setattr(statistics_service, "get_project_stats", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("project stats query should not run")))
    monkeypatch.setattr("worktrace.ui.statistics_view.snapshot_seconds_for_date_range", lambda *_args, **_kwargs: 35)

    StatisticsView.refresh_current_activity(view)

    assert view._summary_labels["total"].config["text"] == "00:00:35"
    assert view._summary_labels["effective"].config["text"] == "00:00:35"
    assert synced[-1][0][0]["total_duration"] == 35
