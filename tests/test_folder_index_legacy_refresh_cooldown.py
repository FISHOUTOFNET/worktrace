from __future__ import annotations

import pytest

from worktrace.services import (
    folder_index_service,
    folder_rule_service,
    project_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def test_failed_enabled_rule_refresh_does_not_consume_cooldown(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Retryable Legacy Refresh")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\RetryableLegacyRefresh",
        project_id,
        True,
    )
    folder_index_service._MISS_REFRESH_TIMES.clear()
    calls: list[int] = []

    def fail_rebuild(value):
        calls.append(int(value))
        raise RuntimeError("transient rebuild enqueue failure")

    monkeypatch.setattr(
        folder_index_service,
        "request_rebuild_for_rule",
        fail_rebuild,
    )
    with pytest.raises(RuntimeError, match="transient rebuild enqueue failure"):
        folder_index_service.request_refresh_for_enabled_rules()

    monkeypatch.setattr(
        folder_index_service,
        "request_rebuild_for_rule",
        lambda value: calls.append(int(value)),
    )
    folder_index_service.request_refresh_for_enabled_rules()

    assert calls == [rule_id, rule_id]
