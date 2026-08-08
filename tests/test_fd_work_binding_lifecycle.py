from __future__ import annotations

import pytest
from types import SimpleNamespace

from worktrace.api import application_capabilities
from worktrace.api.application_capabilities import (
    BackupApplicationService,
    SettingsApplicationService,
)
from worktrace.api.application_lifecycle import ApplicationDataLifecycle
from worktrace.db import CURRENT_SCHEMA_VERSION
from worktrace.services.secure_backup_service import PAYLOAD_VERSION
from worktrace.runtime.application_services import build_application_services


pytestmark = [
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.security_privacy,
    pytest.mark.collector_runtime,
]


class _FDWork:
    def __init__(self):
        self.clear_calls = []

    def clear_all_bindings(self, *, delete_database=False):
        self.clear_calls.append(delete_database)

    def get_settings_status(self):
        return {"enabled": False}

    def after_local_data_cleared(self):
        self.clear_all_bindings(delete_database=True)

    def after_database_replaced(self):
        self.clear_all_bindings(delete_database=False)


def test_clear_all_local_data_deletes_sidecar_only_after_main_clear_succeeds(monkeypatch):
    fd_work = _FDWork()
    service = SettingsApplicationService(
        data_lifecycle=ApplicationDataLifecycle((fd_work,))
    )
    monkeypatch.setattr(
        application_capabilities.settings_api,
        "clear_all_local_data_for_webview",
        lambda _confirm: {"ok": True},
    )

    result = service.clear_all_local_data_for_webview("确认清除")

    assert result["ok"] is True
    assert fd_work.clear_calls == [True]


def test_failed_main_clear_does_not_touch_sidecar(monkeypatch):
    fd_work = _FDWork()
    service = SettingsApplicationService(
        data_lifecycle=ApplicationDataLifecycle((fd_work,))
    )
    monkeypatch.setattr(
        application_capabilities.settings_api,
        "clear_all_local_data_for_webview",
        lambda _confirm: {"ok": False, "error": "failed"},
    )

    service.clear_all_local_data_for_webview("确认清除")

    assert fd_work.clear_calls == []


def test_successful_database_replacement_clears_bindings_but_export_does_not(monkeypatch):
    fd_work = _FDWork()
    service = BackupApplicationService(ApplicationDataLifecycle((fd_work,)))
    monkeypatch.setattr(
        application_capabilities.settings_api,
        "export_encrypted_backup_for_webview",
        lambda *_args: {"ok": True},
    )
    monkeypatch.setattr(
        application_capabilities.settings_api,
        "import_encrypted_backup_for_webview",
        lambda *_args: {"ok": True},
    )

    assert service.export_encrypted_backup_for_webview("out", "pass", "pass")["ok"] is True
    assert fd_work.clear_calls == []
    assert service.import_encrypted_backup_for_webview("in", "pass", "确认导入")["ok"] is True
    assert fd_work.clear_calls == [False]


def test_main_database_and_backup_versions_are_unchanged():
    assert CURRENT_SCHEMA_VERSION == 13
    assert PAYLOAD_VERSION == 6


def test_composition_root_injects_exact_lazy_sidecar_path(tmp_path):
    runtime = SimpleNamespace(paths=SimpleNamespace(base_dir=tmp_path))

    services = build_application_services(runtime)
    path = services.fd_work._binding_service.repository.path

    assert path == tmp_path / "plugins" / "fd_work" / "state.db"
    assert not path.exists()
    services.fd_work.shutdown()
