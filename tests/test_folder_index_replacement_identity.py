from __future__ import annotations

import pytest

from worktrace.data_generation_repository import DataGenerationRepository
from worktrace.db import get_connection
from worktrace.services import folder_index_service, folder_rule_service, project_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def test_miss_refresh_cooldown_isolated_by_database_replacement_epoch(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Replacement Cooldown")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\ReplacementCooldown",
        project_id,
        True,
    )
    folder_index_service._MISS_REFRESH_TIMES.clear()
    rebuilds: list[int] = []
    monkeypatch.setattr(
        folder_index_service,
        "request_rebuild_for_rule",
        lambda candidate: rebuilds.append(int(candidate)),
    )
    monkeypatch.setattr(folder_index_service.time, "monotonic", lambda: 100.0)

    folder_index_service.request_refresh_for_enabled_rules()
    folder_index_service.request_refresh_for_enabled_rules()
    assert rebuilds == [rule_id]

    with get_connection() as conn:
        DataGenerationRepository.bump_replacement(conn)
        conn.commit()

    folder_index_service.request_refresh_for_enabled_rules()
    assert rebuilds == [rule_id, rule_id]
