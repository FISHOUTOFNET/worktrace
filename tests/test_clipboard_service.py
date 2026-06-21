from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, clipboard_service, project_service, rule_service


def test_clipboard_capture_defaults_to_disabled(temp_db):
    assert clipboard_service.is_capture_enabled() is False


def test_clipboard_text_keyword_classifies_source_activity(temp_db):
    project = project_service.create_project("Client")
    rule_service.create_rule("Acme", project)
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)

    event_id = clipboard_service.record_clipboard_event(
        activity,
        "Copied Acme contract clause",
        ActiveWindow("Edge", "msedge.exe", "Research"),
        copied_at="2026-06-18 09:00:05",
        sequence_number=101,
    )

    row = activity_service.get_activity(activity)
    with get_connection() as conn:
        event_count = conn.execute("SELECT COUNT(*) AS c FROM activity_clipboard_event").fetchone()["c"]
        assignment = conn.execute(
            "SELECT source, confidence FROM activity_project_assignment WHERE activity_id = ?",
            (activity,),
        ).fetchone()
    assert event_id is not None
    assert event_count == 1
    assert row["project_id"] == project
    assert assignment["source"] == "keyword_rule"
    assert assignment["confidence"] == 80


def test_clipboard_event_deduplicates_sequence_number(temp_db):
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)
    window = ActiveWindow("Edge", "msedge.exe", "Research")

    first = clipboard_service.record_clipboard_event(
        activity,
        "same text",
        window,
        copied_at="2026-06-18 09:00:05",
        sequence_number=42,
    )
    second = clipboard_service.record_clipboard_event(
        activity,
        "same text",
        window,
        copied_at="2026-06-18 09:00:06",
        sequence_number=42,
    )

    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM activity_clipboard_event").fetchone()["c"]
    assert second == first
    assert count == 1


def test_clipboard_retention_keeps_only_last_month(temp_db):
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)
    with get_connection() as conn:
        for copied_at, copied_text in [
            ("2026-05-01 09:00:00", "old"),
            ("2026-06-01 09:00:00", "new"),
        ]:
            conn.execute(
                """
                INSERT INTO activity_clipboard_event(
                    activity_id, copied_at, app_name, process_name, window_title,
                    copied_text, text_hash, text_length, created_at, updated_at
                )
                VALUES (?, ?, 'Edge', 'msedge.exe', 'Research', ?, ?, ?, ?, ?)
                """,
                (activity, copied_at, copied_text, copied_text, len(copied_text), copied_at, copied_at),
            )

    deleted = clipboard_service.prune_old_events(now="2026-06-18 09:00:00")

    with get_connection() as conn:
        rows = conn.execute("SELECT copied_text FROM activity_clipboard_event ORDER BY copied_at").fetchall()
    assert deleted == 1
    assert [row["copied_text"] for row in rows] == ["new"]


def test_file_text_mappings_include_activity_file_path(temp_db):
    activity = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx - Word",
        file_path_hint="D:\\Client\\Spec.docx",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)
    clipboard_service.record_clipboard_event(
        activity,
        "useful copied paragraph",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\Client\\Spec.docx"),
        copied_at="2026-06-18 09:00:05",
    )

    rows = clipboard_service.list_file_text_mappings("2026-06-18 00:00:00", "2026-06-18 23:59:59")

    assert rows[0]["file_path"] == "D:\\Client\\Spec.docx"
    assert rows[0]["copied_text"] == "useful copied paragraph"
