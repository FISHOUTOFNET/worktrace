from __future__ import annotations

import sqlite3
import os
from pathlib import Path
import subprocess
import sys
import pytest

from scripts import fd_work_windows_acceptance as acceptance
from worktrace.integrations.fd_work.binding_repository import FDWorkBindingRepository
from worktrace.integrations.fd_work.case_identity import case_label_hash


pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.security_privacy]


def _state(tmp_path):
    return {
        "exact_sha": "a" * 40,
        "pywebview_version": "6.2.1",
        "started_at": 100.0,
        "database_path": str(tmp_path / "main.db"),
        "sidecar_path": str(tmp_path / "state.db"),
        "baseline_project_ids": [],
        "project_created": False,
        "binding_created": False,
        "binding_readback": False,
        "restart_readback": False,
        "helper_foreground_count": 0,
    }


def _insert_bound_project(state, project_id: int, label: str) -> None:
    created_at = f"2026-08-04T00:00:{project_id:02d}+00:00"
    with sqlite3.connect(state["database_path"]) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            "INSERT INTO project(id, name, created_at, created_by) VALUES (?, ?, ?, 'user')",
            (project_id, label, created_at),
        )
    FDWorkBindingRepository(state["sidecar_path"]).bind_project(
        project_id,
        created_at,
        case_label_hash(label),
        5,
    )


def test_candidate_requires_exact_main_and_sidecar_identity(tmp_path):
    state = _state(tmp_path)
    _insert_bound_project(state, 41, "TEST MATTER A")

    candidate = acceptance._candidate(state)

    assert candidate == {
        "project_id": 41,
        "created_at": "2026-08-04T00:00:41+00:00",
        "name_hash": case_label_hash("TEST MATTER A"),
    }
    assert "name" not in candidate


def test_candidate_fails_closed_when_more_than_one_new_binding_matches(tmp_path):
    state = _state(tmp_path)
    _insert_bound_project(state, 41, "TEST MATTER A")
    _insert_bound_project(state, 42, "TEST MATTER B")

    with pytest.raises(RuntimeError, match="multiple_candidates"):
        acceptance._candidate(state)


def test_safe_result_has_only_approved_fields(tmp_path, monkeypatch):
    state = _state(tmp_path)
    monkeypatch.setattr(acceptance.time, "monotonic", lambda: 101.5)

    result = acceptance._safe_result(state, None)

    assert tuple(result) == acceptance._SAFE_KEYS
    assert result["elapsed_ms"] == 1500
    assert not ({"project_id", "created_at", "name_hash"} & result.keys())


def test_cleanup_uses_the_public_database_configurator():
    source = acceptance.Path(acceptance.__file__).read_text(encoding="utf-8")

    assert "db.configure_database(database_path)" in source
    assert "db.configure(database_path)" not in source


def test_script_entrypoint_resolves_worktrace_outside_repository(tmp_path):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(Path(acceptance.__file__)), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "verify-restart" in completed.stdout
