import json

from worktrace.services import settings_service
from worktrace.ui.overview_view import OverviewView, current_activity_text


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
