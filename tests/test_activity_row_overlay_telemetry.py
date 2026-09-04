from __future__ import annotations

import logging
from types import SimpleNamespace

from worktrace.services import activity_row_overlay as overlay


def _visible_timeline_span(*, live_clock: dict | None = None) -> dict:
    return {
        "anchor_activity_id": 42,
        "is_visible_in_timeline": True,
        "is_visible_in_recent": True,
        "is_visible_in_details": True,
        "live_clock": live_clock or {},
    }


def test_expected_live_owner_degradation_logs_only_structural_diagnostics(
    monkeypatch,
    caplog,
):
    context = SimpleNamespace(
        runtime_consistent=True,
        verified_open_activity_id=42,
    )
    monkeypatch.setattr(
        overlay,
        "current_page_read_context",
        lambda: context,
    )
    row = {
        "activity_ids": [42],
        "is_in_progress": True,
        "closed_duration_seconds": 3,
        "duration_seconds": 3,
        "window_title": "PRIVATE TITLE",
        "project_name": "PRIVATE PROJECT",
        "file_path_hint": r"C:\\private\\secret.docx",
    }

    with caplog.at_level(logging.WARNING, logger=overlay.__name__):
        overlay.apply_live_span_to_row(
            row,
            _visible_timeline_span(),
            row_kind=overlay.ROW_KIND_PROJECT_SESSION_ROW,
        )

    assert "live projection overlay degraded" in caplog.text
    assert "reason=source_clock_invalid" in caplog.text
    assert "row_kind=project_session_row" in caplog.text
    assert "PRIVATE TITLE" not in caplog.text
    assert "PRIVATE PROJECT" not in caplog.text
    assert "secret.docx" not in caplog.text


def test_unrelated_closed_row_does_not_emit_live_degradation_warning(
    monkeypatch,
    caplog,
):
    context = SimpleNamespace(
        runtime_consistent=True,
        verified_open_activity_id=42,
    )
    monkeypatch.setattr(
        overlay,
        "current_page_read_context",
        lambda: context,
    )
    row = {
        "activity_ids": [7],
        "is_in_progress": False,
        "closed_duration_seconds": 10,
        "duration_seconds": 10,
    }

    with caplog.at_level(logging.WARNING, logger=overlay.__name__):
        overlay.apply_live_span_to_row(
            row,
            _visible_timeline_span(),
            row_kind=overlay.ROW_KIND_PROJECT_SESSION_ROW,
        )

    assert "live projection overlay degraded" not in caplog.text
