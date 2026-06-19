import json

from worktrace.services import settings_service
from worktrace.ui.overview_view import current_activity_text


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
