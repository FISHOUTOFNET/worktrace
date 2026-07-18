from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from worktrace import db
from worktrace.services import activity_inference_job_repository as jobs
from worktrace.services import secure_backup_service
from worktrace.schema_migrations import migrate_10_to_11

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]


def _v4_tables() -> dict[str, list[dict]]:
    return {name: [] for name in secure_backup_service._V4_EXPORT_TABLES}


def _payload(
    version: int,
    schema_version: str,
    fingerprint: str,
    tables: dict[str, list[dict]],
) -> bytes:
    return json.dumps(
        {
            "format": secure_backup_service.PAYLOAD_FORMAT,
            "version": version,
            "schema_version": schema_version,
            "schema_fingerprint": fingerprint,
            "tables": tables,
        },
        separators=(",", ":"),
    ).encode("utf-8")


def test_v10_migration_converts_only_real_legacy_retry_sentinels():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE activity_log (
            id INTEGER PRIMARY KEY,
            end_time TEXT,
            status TEXT NOT NULL,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE activity_project_assignment (
            activity_id INTEGER PRIMARY KEY,
            confidence INTEGER NOT NULL,
            source TEXT NOT NULL,
            is_manual INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        INSERT INTO activity_log VALUES
            (1, '2026-07-18 10:00:00', 'normal', 0, 0),
            (2, '2026-07-18 10:00:00', 'normal', 0, 0),
            (3, '2026-07-18 10:00:00', 'normal', 0, 0),
            (4, NULL, 'normal', 0, 0);
        INSERT INTO activity_project_assignment VALUES
            (1, -1, 'uncategorized', 0, '2026-07-18 10:00:00'),
            (2, 0, 'uncategorized', 0, '2026-07-18 10:00:00'),
            (3, -1, 'uncategorized', 1, '2026-07-18 10:00:00'),
            (4, -1, 'uncategorized', 0, '2026-07-18 10:00:00');
        """
    )

    migrate_10_to_11(conn)

    rows = conn.execute(
        "SELECT activity_id, reason, status FROM activity_inference_job ORDER BY activity_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(1, "legacy_retry", "pending")]
    confidence = {
        int(row["activity_id"]): int(row["confidence"])
        for row in conn.execute(
            "SELECT activity_id, confidence FROM activity_project_assignment"
        ).fetchall()
    }
    assert confidence == {1: 0, 2: 0, 3: 0, 4: 0}


def test_job_repository_requires_closed_enum_boundaries():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(TypeError, match="inference_job_reason_required"):
        jobs.enqueue_closed_activity_ids(
            conn,
            [],
            reason="closed_activity",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="inference_failure_code_required"):
        jobs.record_failure(
            conn,
            1,
            "unexpected_failure",  # type: ignore[arg-type]
        )


def test_job_schema_has_no_running_or_recovery_state():
    schema = (ROOT / "worktrace/schema_internal.sql").read_text(encoding="utf-8")
    repository = (
        ROOT / "worktrace/services/activity_inference_job_repository.py"
    ).read_text(encoding="utf-8")
    assert "status IN ('pending', 'failed')" in schema
    assert "'running'" not in schema
    assert "recover_interrupted" not in repository
    assert "EXECUTION_LOCK" not in repository


def test_backup_payload_matrix_accepts_only_published_combinations():
    v5_tables = {name: [] for name in secure_backup_service.EXPORT_TABLES}
    current = secure_backup_service._parse_and_validate_payload(
        _payload(
            5,
            secure_backup_service.SCHEMA_VERSION,
            secure_backup_service._core.expected_schema_fingerprint(),
            v5_tables,
        )
    )
    assert current["version"] == 5

    legacy10 = secure_backup_service._parse_and_validate_payload(
        _payload(
            4,
            "10",
            secure_backup_service._legacy_v10_schema_fingerprint(),
            _v4_tables(),
        )
    )
    assert legacy10["tables"]["activity_inference_job"] == []

    legacy8 = secure_backup_service._parse_and_validate_payload(
        _payload(
            4,
            "8",
            secure_backup_service._V4_SCHEMA8_FINGERPRINT,
            _v4_tables(),
        )
    )
    assert legacy8["tables"]["activity_inference_job"] == []

    with pytest.raises(secure_backup_service.BackupVersionNotSupportedError):
        secure_backup_service._parse_and_validate_payload(
            _payload(
                4,
                secure_backup_service.SCHEMA_VERSION,
                secure_backup_service._core.expected_schema_fingerprint(),
                _v4_tables(),
            )
        )


def test_runtime_starts_collector_before_optional_inference_worker():
    runtime = (ROOT / "worktrace/runtime/app_runtime.py").read_text(encoding="utf-8")
    lifecycle = (
        ROOT / "worktrace/services/activity_lifecycle_service.py"
    ).read_text(encoding="utf-8")
    assignment = (
        ROOT / "worktrace/services/assignment_command_service.py"
    ).read_text(encoding="utf-8")

    assert "retry_pending_inference" not in runtime
    assert runtime.index("self.start_collector()") < runtime.index(
        "self.start_background_workers()"
    )
    assert "_inference_thread" in runtime
    assert "_enqueue_closed_inference_jobs" in lifecycle
    assert "INFERENCE_RETRY_CONFIDENCE" not in assignment
    assert "activity_inference_job" not in assignment


def test_phase_2_published_versions_are_explicit():
    assert db.CURRENT_SCHEMA_VERSION == 11
    assert secure_backup_service.PAYLOAD_VERSION == 5
