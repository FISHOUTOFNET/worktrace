from __future__ import annotations

from pathlib import Path

from worktrace.report_generation_classifier import (
    ReportStructureSqlClassification,
    classify_report_structure_sql,
    sql_affects_report_structure,
)


def test_database_connection_does_not_define_report_policy_tables():
    source = Path("worktrace/db.py").read_text(encoding="utf-8")
    assert "_REPORT_STRUCTURE_TABLES" not in source
    assert "_REPORT_STRUCTURE_SETTINGS" not in source
    assert "def _classify_report_structure_sql" not in source


def test_classifier_ignores_open_duration_checkpoint():
    sql = "UPDATE activity_log SET duration_seconds = ?, updated_at = ? WHERE id = ?"
    assert classify_report_structure_sql(sql) is ReportStructureSqlClassification.NONE
    assert sql_affects_report_structure(sql, (30, "2026-07-17 09:00:00", 1)) is False


def test_classifier_tracks_structural_activity_and_report_setting_changes():
    assert sql_affects_report_structure(
        "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
        ("idle", "2026-07-17 09:00:00", 1),
    ) is True
    assert sql_affects_report_structure(
        "UPDATE settings SET value = ? WHERE key = ?",
        ("20", "context_carry_minutes"),
    ) is True
    assert sql_affects_report_structure(
        "UPDATE settings SET value = ? WHERE key = ?",
        ("running", "collector_status"),
    ) is False
