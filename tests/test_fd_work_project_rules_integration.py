from __future__ import annotations

import pytest

from worktrace.api import application_capabilities
from worktrace.api.application_capabilities import RulesApplicationService
from worktrace.integrations.fd_work.contracts import FDWorkEntryError


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _FDWork:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.discarded = []

    def get_settings_status(self):
        return {"enabled": self.enabled}

    def validate_case_selection(self, token, expected):
        if not token:
            raise FDWorkEntryError("case_selection_required")
        if token == "expired":
            raise FDWorkEntryError("case_selection_expired")
        if expected != "CASE A":
            raise FDWorkEntryError("case_selection_mismatch")
        return "CASE A"

    def discard_case_selection(self, token):
        self.discarded.append(token)


def test_enabled_create_requires_selection_and_uses_canonical_label(monkeypatch):
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *args: writes.append(args) or {"ok": True, "project": {"id": 1}},
    )
    fd_work = _FDWork()
    service = RulesApplicationService(fd_work=fd_work)

    missing = service.create_project_for_rules("CASE A", "", "中文")
    created = service.create_project_for_rules("CASE A", "", "中文", "token")

    assert missing == {"ok": False, "error": "case_selection_required"}
    assert writes == [("CASE A", "", "中文")]
    assert created["ok"] is True
    assert fd_work.discarded == ["token"]


def test_enabled_rename_requires_selection_but_description_only_edit_does_not(monkeypatch):
    monkeypatch.setattr(
        application_capabilities.project_api,
        "get_project",
        lambda _project_id: {"id": 7, "name": "CASE A"},
    )
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "update_project_for_rules",
        lambda *args: writes.append(args) or {"ok": True, "project": {"id": 7}},
    )
    service = RulesApplicationService(fd_work=_FDWork())

    unchanged = service.update_project_for_rules(7, "CASE A", "new", "中文")
    renamed = service.update_project_for_rules(7, "CASE B", "new", "中文")

    assert unchanged["ok"] is True
    assert renamed == {"ok": False, "error": "case_selection_required"}
    assert writes == [(7, "CASE A", "new", "中文")]


def test_disabled_capability_keeps_free_text_create_and_rename(monkeypatch):
    writes = []
    monkeypatch.setattr(
        application_capabilities.project_api,
        "get_project",
        lambda _project_id: {"id": 7, "name": "Old"},
    )
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *args: writes.append(("create", args)) or {"ok": True},
    )
    monkeypatch.setattr(
        application_capabilities.project_api,
        "update_project_for_rules",
        lambda *args: writes.append(("update", args)) or {"ok": True},
    )
    service = RulesApplicationService(fd_work=_FDWork(enabled=False))

    assert service.create_project_for_rules("Free", "", "中文")["ok"] is True
    assert service.update_project_for_rules(7, "Renamed", "", "中文")["ok"] is True
    assert writes == [
        ("create", ("Free", "", "中文")),
        ("update", (7, "Renamed", "", "中文")),
    ]


def test_failed_project_write_retains_selection_for_retry(monkeypatch):
    monkeypatch.setattr(
        application_capabilities.project_api,
        "create_project_for_rules",
        lambda *_args: {"ok": False, "error": "duplicate_project_name"},
    )
    fd_work = _FDWork()

    result = RulesApplicationService(fd_work=fd_work).create_project_for_rules(
        "CASE A", "", "中文", "token"
    )

    assert result["error"] == "duplicate_project_name"
    assert fd_work.discarded == []
