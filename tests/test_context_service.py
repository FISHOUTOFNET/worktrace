from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, clipboard_service, context_service, project_service
from worktrace.services.context_service import recompute_context_assignments_for_date


def _activity(app, process, title, start, project_id=None, status="normal"):
    aid = activity_service.create_activity(
        app,
        process,
        title,
        start_time=f"2026-06-18 {start}",
        project_id=project_id,
        status=status,
    )
    activity_service.finalize_created_activity(aid)
    return aid


def test_same_project_different_anchor_files_classify_auxiliary(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(browser)["project_id"] == project


def test_generic_app_between_same_project_anchors_uses_same_context_carry(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    trae = _activity("Trae CN.exe", "Trae CN.exe", "db.py - WorkTrace - Trae CN", "09:10:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    recompute_context_assignments_for_date("2026-06-18")

    row = activity_service.get_activity(trae)
    assert row["project_id"] == project


def test_uncategorized_anchor_stops_context_scan(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    unassigned_anchor = _activity("Word", "winword.exe", "Loose_file.docx", "09:05:00")
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(unassigned_anchor)["project_name"] == UNCATEGORIZED_PROJECT
    assert activity_service.get_activity(browser)["project_name"] == UNCATEGORIZED_PROJECT


def test_same_project_anchors_classify_auxiliary_without_carry_window_limit(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    browser = _activity("Edge", "msedge.exe", "Search", "12:00:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "15:00:00", project)
    activity_service.close_current_open_record("2026-06-18 15:10:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(browser)["project_id"] == project


def test_next_anchor_classifies_auxiliary_inside_carry_window(temp_db):
    project = project_service.create_project("A")
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Word", "winword.exe", "A_file.docx", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(browser)["project_id"] == project


def test_next_anchor_does_not_classify_auxiliary_outside_carry_window(temp_db):
    project = project_service.create_project("A")
    browser = _activity("Edge", "msedge.exe", "Search", "09:00:00")
    _activity("Word", "winword.exe", "A_file.docx", "09:30:00", project)
    activity_service.close_current_open_record("2026-06-18 09:40:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(browser)["project_name"] == UNCATEGORIZED_PROJECT


def test_different_project_anchors_leave_auxiliary_uncategorized(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project_a)
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Word", "winword.exe", "B_file.docx", "09:20:00", project_b)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(browser)["project_name"] == UNCATEGORIZED_PROJECT


def test_interrupt_and_carry_window_stop_context(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project)
    interrupted = _activity("空闲", "idle", "用户空闲", "09:05:00", status="idle")
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    late = _activity("Edge", "msedge.exe", "Later Search", "09:40:00")
    activity_service.close_current_open_record("2026-06-18 09:45:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(interrupted)["project_name"] == UNCATEGORIZED_PROJECT
    assert activity_service.get_activity(browser)["project_name"] == UNCATEGORIZED_PROJECT
    assert activity_service.get_activity(late)["project_name"] == UNCATEGORIZED_PROJECT


def test_excluded_and_error_do_not_stop_context_scan(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project)
    _activity("已排除", "excluded", "已排除窗口", "09:05:00", status="excluded")
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("异常", "error", "采集异常", "09:15:00", status="error")
    _activity("Word", "winword.exe", "A_file_2.docx", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(browser)["project_id"] == project


def test_recompute_is_idempotent_and_preserves_manual_auxiliary(temp_db):
    project = project_service.create_project("A")
    manual_project = project_service.create_project("Manual")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project)
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Word", "winword.exe", "A_file_2.docx", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")
    activity_service.update_activity_project(browser, manual_project, manual=True)

    recompute_context_assignments_for_date("2026-06-18")
    first = activity_service.get_activity(browser)
    recompute_context_assignments_for_date("2026-06-18")
    second = activity_service.get_activity(browser)

    assert first["project_id"] == manual_project
    assert second["project_id"] == manual_project
    assert second["updated_at"] == first["updated_at"]


def test_recompute_context_skips_when_date_fingerprint_is_unchanged(temp_db, monkeypatch):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project)
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Word", "winword.exe", "A_file_2.docx", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")
    calls = []
    original = context_service._load_rows

    def counted_load_rows(start: str, end: str):
        calls.append((start, end))
        return original(start, end)

    monkeypatch.setattr(context_service, "_load_rows", counted_load_rows)

    recompute_context_assignments_for_date("2026-06-18")
    first_call_count = len(calls)
    recompute_context_assignments_for_date("2026-06-18")

    assert first_call_count > 0
    assert len(calls) == first_call_count
    assert activity_service.get_activity(browser)["project_id"] == project


def test_recompute_context_runs_again_when_date_fingerprint_changes(temp_db, monkeypatch):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project)
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Word", "winword.exe", "A_file_2.docx", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")
    calls = []
    original = context_service._load_rows

    def counted_load_rows(start: str, end: str):
        calls.append((start, end))
        return original(start, end)

    monkeypatch.setattr(context_service, "_load_rows", counted_load_rows)

    recompute_context_assignments_for_date("2026-06-18")
    first_call_count = len(calls)
    _activity("Word", "winword.exe", "A_file_3.docx", "09:40:00", project)
    activity_service.close_current_open_record("2026-06-18 09:50:00")
    recompute_context_assignments_for_date("2026-06-18")

    assert len(calls) > first_call_count
    assert activity_service.get_activity(browser)["project_id"] == project


def test_clipboard_transition_context_beats_anchor_context(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project_a)
    source = _activity("Edge", "msedge.exe", "B Dashboard", "09:04:00", project_b)
    target = _activity("Edge", "msedge.exe", "Search", "09:04:08")
    _activity("Word", "winword.exe", "A_file_2.docx", "09:10:00", project_a)
    activity_service.close_current_open_record("2026-06-18 09:20:00")
    activity_service.update_activity_project(target, project_a, manual=False)
    clipboard_service.record_clipboard_event(
        source,
        "copied from B",
        ActiveWindow("Edge", "msedge.exe", "B Dashboard"),
        copied_at="2026-06-18 09:04:03",
    )

    recompute_context_assignments_for_date("2026-06-18")

    row = activity_service.get_activity(target)
    assert row["project_id"] == project_b
    with context_service.get_connection() as conn:
        assignment = conn.execute(
            "SELECT source, confidence FROM activity_project_assignment WHERE activity_id = ?",
            (target,),
        ).fetchone()
    assert assignment["source"] == "clipboard_transition_context"
    assert assignment["confidence"] == 70


def test_clipboard_transition_does_not_override_direct_conflict(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    source = _activity("Edge", "msedge.exe", "B Dashboard", "09:00:00", project_b)
    target = _activity("Word", "winword.exe", "A_file.docx", "09:00:08", project_a)
    activity_service.close_current_open_record("2026-06-18 09:10:00")
    clipboard_service.record_clipboard_event(
        source,
        "copied from B",
        ActiveWindow("Edge", "msedge.exe", "B Dashboard"),
        copied_at="2026-06-18 09:00:03",
    )

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(target)["project_id"] == project_a


def test_clipboard_transition_expires_after_ten_seconds(temp_db):
    project_b = project_service.create_project("B")
    source = _activity("Edge", "msedge.exe", "B Dashboard", "09:00:00", project_b)
    target = _activity("Edge", "msedge.exe", "Search", "09:00:20")
    activity_service.close_current_open_record("2026-06-18 09:10:00")
    clipboard_service.record_clipboard_event(
        source,
        "copied from B",
        ActiveWindow("Edge", "msedge.exe", "B Dashboard"),
        copied_at="2026-06-18 09:00:03",
    )

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(target)["project_name"] == UNCATEGORIZED_PROJECT


# --- Short-gap same-project anchor bridging ---------------------------
# When a brief uncategorized context anchor (e.g. a short .doc / .docx
# Word activity) is sandwiched between two same-project anchors with a
# total middle duration under ``REPORT_CONTEXT_SHORT_MERGE_SECONDS``
# (5 * 60 = 300s), the middle anchor is bridged to the surrounding
# project using the existing ``anchor_context`` source. This covers the
# real-world bug where ``_is_context_anchor(row)`` caused a direct
# ``continue`` in the main loop, leaving the short Word document
# uncategorized and also blocking context carry for later auxiliary
# activities. The bridging is persisted to ``activity_project_assignment``
# and synced to ``activity_log.project_id``.


def test_short_gap_same_project_bridges_middle_word_docx(temp_db):
    """A short uncategorized .docx anchor between two same-project anchors
    is bridged to the surrounding project."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:03:00", project)
    activity_service.close_current_open_record("2026-06-18 09:05:00")

    recompute_context_assignments_for_date("2026-06-18")

    row = activity_service.get_activity(middle)
    assert row["project_id"] == project
    assert row["project_name"] == "A"


def test_short_gap_middle_anchor_is_resource_anchor(temp_db):
    """The middle .docx row must be a context anchor (resource_is_anchor=true
    and extension in ANCHOR_FILE_EXTENSIONS). This confirms the bridging
    covers the 'middle row itself is a context anchor' scenario."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:03:00", project)
    activity_service.close_current_open_record("2026-06-18 09:05:00")

    row = activity_service.get_activity(middle)
    assert row.get("resource_is_anchor") is True
    # Confirm the display name ends with .docx (in ANCHOR_FILE_EXTENSIONS).
    display_name = str(row.get("resource_display_name") or "")
    assert display_name.lower().endswith(".docx")


def test_short_gap_middle_anchor_not_skipped_by_is_context_anchor(temp_db):
    """The middle context anchor row must NOT be skipped by
    ``_is_context_anchor(row)`` in the short-gap bridging pass. This is
    verified by confirming the middle anchor gets bridged (if it were
    skipped, it would stay uncategorized)."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:03:00", project)
    activity_service.close_current_open_record("2026-06-18 09:05:00")

    recompute_context_assignments_for_date("2026-06-18")

    # If _is_context_anchor caused a skip in the bridging pass, the middle
    # would stay uncategorized. Assert it was bridged.
    assert activity_service.get_activity(middle)["project_id"] == project


def test_short_gap_persists_assignment_with_anchor_context_source(temp_db):
    """The bridging must persist to ``activity_project_assignment`` with
    source ``anchor_context`` and sync ``activity_log.project_id``."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:03:00", project)
    activity_service.close_current_open_record("2026-06-18 09:05:00")

    recompute_context_assignments_for_date("2026-06-18")

    # activity_log.project_id must be synced.
    log_row = activity_service.get_activity(middle)
    assert log_row["project_id"] == project
    # activity_project_assignment must have source=anchor_context.
    with context_service.get_connection() as conn:
        assignment = conn.execute(
            "SELECT source, confidence FROM activity_project_assignment "
            "WHERE activity_id = ?",
            (middle,),
        ).fetchone()
    assert assignment is not None
    assert assignment["source"] == "anchor_context"
    assert assignment["confidence"] == 60


def test_short_gap_exceeding_threshold_does_not_bridge(temp_db):
    """When the total middle duration exceeds
    ``REPORT_CONTEXT_SHORT_MERGE_SECONDS`` (300s), the middle anchor is
    NOT bridged."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    # 09:01:00 → 09:10:00 = 540s > 300s threshold
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:10:00", project)
    activity_service.close_current_open_record("2026-06-18 09:15:00")

    recompute_context_assignments_for_date("2026-06-18")

    row = activity_service.get_activity(middle)
    assert row["project_name"] == UNCATEGORIZED_PROJECT


def test_short_gap_different_project_anchors_do_not_bridge(temp_db):
    """When the two surrounding anchors belong to different projects, the
    middle anchor is NOT bridged."""
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project_a)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    _activity("Word", "winword.exe", "B_file.docx", "09:03:00", project_b)
    activity_service.close_current_open_record("2026-06-18 09:05:00")

    recompute_context_assignments_for_date("2026-06-18")

    row = activity_service.get_activity(middle)
    assert row["project_name"] == UNCATEGORIZED_PROJECT


def test_short_gap_does_not_override_manual_assignment(temp_db):
    """A manual assignment on the middle anchor must NOT be overwritten
    by short-gap bridging."""
    project = project_service.create_project("A")
    manual_project = project_service.create_project("Manual")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:03:00", project)
    activity_service.close_current_open_record("2026-06-18 09:05:00")
    # Manually assign the middle to a different project.
    activity_service.update_activity_project(middle, manual_project, manual=True)

    recompute_context_assignments_for_date("2026-06-18")

    row = activity_service.get_activity(middle)
    assert row["project_id"] == manual_project
    with context_service.get_connection() as conn:
        assignment = conn.execute(
            "SELECT source FROM activity_project_assignment WHERE activity_id = ?",
            (middle,),
        ).fetchone()
    assert assignment["source"] == "manual"


def test_short_gap_paused_interrupt_prevents_bridging(temp_db):
    """A paused activity between the middle anchor and the next anchor
    prevents bridging (``_find_next_anchor`` returns None on interrupt)."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    _activity("已暂停", "paused", "用户暂停", "09:02:00", status="paused")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:03:00", project)
    activity_service.close_current_open_record("2026-06-18 09:05:00")

    recompute_context_assignments_for_date("2026-06-18")

    row = activity_service.get_activity(middle)
    assert row["project_name"] == UNCATEGORIZED_PROJECT


def test_short_gap_idle_interrupt_prevents_bridging(temp_db):
    """An idle activity between the middle anchor and the next anchor
    prevents bridging."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    _activity("空闲", "idle", "用户空闲", "09:02:00", status="idle")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:03:00", project)
    activity_service.close_current_open_record("2026-06-18 09:05:00")

    recompute_context_assignments_for_date("2026-06-18")

    row = activity_service.get_activity(middle)
    assert row["project_name"] == UNCATEGORIZED_PROJECT


def test_short_gap_hidden_middle_prevents_bridging(temp_db):
    """A hidden middle activity prevents bridging (all middle activities
    must be visible)."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle = _activity("Word", "winword.exe", "Loose_file.docx", "09:01:00")
    activity_service.close_current_open_record("2026-06-18 09:05:00")
    # Hide the middle activity after closing.
    activity_service.hide_activity(middle)
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:06:00", project)
    activity_service.close_current_open_record("2026-06-18 09:08:00")

    recompute_context_assignments_for_date("2026-06-18")

    # Hidden middle should not be bridged.
    row = activity_service.get_activity(middle)
    assert row["project_name"] == UNCATEGORIZED_PROJECT


def test_short_gap_bridges_multiple_middle_anchors(temp_db):
    """Multiple short middle anchors between the same-project anchors are
    all bridged when the total duration is under the threshold."""
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    middle1 = _activity("Word", "winword.exe", "Loose_1.docx", "09:01:00")
    middle2 = _activity("Word", "winword.exe", "Loose_2.docx", "09:02:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:04:00", project)
    activity_service.close_current_open_record("2026-06-18 09:06:00")

    recompute_context_assignments_for_date("2026-06-18")

    # Total middle duration: 09:01:00 → 09:04:00 = 180s < 300s
    assert activity_service.get_activity(middle1)["project_id"] == project
    assert activity_service.get_activity(middle2)["project_id"] == project
