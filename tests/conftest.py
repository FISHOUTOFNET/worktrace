from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worktrace import db


@pytest.fixture()
def temp_db(tmp_path):
    path = tmp_path / "worktrace.db"
    db.initialize_database(path)
    return path


def pytest_collection_modifyitems(items) -> None:
    """Upgrade the legacy backup seed to a real immutable operation ledger.

    The original fixture used arbitrary 40-character revisions, which was only
    possible while staging validation ignored replay conflicts. Keep the broad
    fixture data but replace that fabricated operation through the production
    mutation UOW before each test consumes it.
    """
    modules = {item.module for item in items if item.module.__name__.endswith("test_secure_backup_service")}
    for module in modules:
        original = module._seed_test_data
        if getattr(original, "_valid_operation_fixture", False):
            continue

        def seed_valid_operation_fixture(*, _module=module, _original=original) -> None:
            _original()
            from worktrace.db import get_connection
            from worktrace.services import report_session_operation_service as mutations
            from worktrace.services.report_projection_snapshot_service import build_visible_snapshot

            with get_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM project WHERE name = ?",
                    (_module.TEST_PROJECT_NAME,),
                ).fetchone()
                project_id = int(row["id"])
                conn.execute("DELETE FROM report_mutation_request WHERE request_id = 'backup-seed-edit'")
                operation_rows = conn.execute(
                    "SELECT id FROM report_session_operation WHERE report_date = '2026-06-25'"
                ).fetchall()
                operation_ids = [int(item["id"]) for item in operation_rows]
                if operation_ids:
                    placeholders = ",".join("?" for _ in operation_ids)
                    conn.execute(
                        f"DELETE FROM report_session_operation_member WHERE operation_id IN ({placeholders})",
                        operation_ids,
                    )
                    conn.execute(
                        f"DELETE FROM report_session_operation WHERE id IN ({placeholders})",
                        operation_ids,
                    )

            source = build_visible_snapshot("2026-06-25", "2026-06-25").final_sessions[0]
            result = mutations.edit_session(
                "2026-06-25",
                str(source["projection_instance_key"]),
                str(source["projection_revision"]),
                "backup-seed-edit",
                project_id=project_id,
                adjusted_duration_seconds=60,
                note=_module.TEST_NOTE,
            )
            assert result.outcome_type == "operation_committed"

        seed_valid_operation_fixture._valid_operation_fixture = True
        module._seed_test_data = seed_valid_operation_fixture
