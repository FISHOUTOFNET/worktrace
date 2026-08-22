from __future__ import annotations

import pytest

from worktrace.runtime.post_privacy_startup import PostPrivacyStartupCoordinator


pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.security_privacy,
    pytest.mark.contract,
    pytest.mark.collector_runtime,
]


class _AppControl:
    def __init__(self, allowed):
        self.allowed = allowed
        self.calls = 0

    def start_collection_after_privacy_gate(self):
        self.calls += 1
        return {"ok": self.allowed, "error": None if self.allowed else "请先确认隐私说明"}

    def accept_privacy_notice_and_start(self):
        self.calls += 1
        return {
            "ok": self.allowed,
            "accepted": True,
            "collector_started": self.allowed,
        }

    def get_collection_status(self):
        return {"ok": True, "status": "running" if self.allowed else "error"}


class _FDWork:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.authorizations = []
        self.prepare_calls = []

    def set_privacy_authorized(self, authorized):
        self.authorizations.append(authorized)

    def prepare_after_privacy(self, *, pre_start):
        if self.enabled:
            self.prepare_calls.append(
                ("prestart" if pre_start else "runtime", False)
            )


def test_unaccepted_privacy_never_authorizes_or_prepares_fd_work():
    app_control = _AppControl(False)
    fd_work = _FDWork()
    coordinator = PostPrivacyStartupCoordinator(
        app_control, participants=(fd_work,), privacy_authorized_reader=lambda: False
    )

    result = coordinator.start_if_authorized(pre_start=True)

    assert result["ok"] is False
    assert fd_work.authorizations == [False]
    assert fd_work.prepare_calls == []


def test_pre_webview_phase_authorizes_without_preparing_participants():
    app_control = _AppControl(True)
    fd_work = _FDWork()
    coordinator = PostPrivacyStartupCoordinator(
        app_control, participants=(fd_work,), privacy_authorized_reader=lambda: True
    )

    prestart = coordinator.prepare_before_webview_start()

    assert prestart == {
        "ok": True,
        "authorized": True,
        "prepared": False,
        "error": None,
    }
    assert app_control.calls == 0
    assert fd_work.authorizations == [True]
    assert fd_work.prepare_calls == []

    started = coordinator.start_if_authorized(pre_start=False)

    assert started["ok"] is True
    assert app_control.calls == 1
    assert fd_work.authorizations == [True, True]
    assert fd_work.prepare_calls == [("runtime", False)]


def test_authorized_start_is_idempotent_and_selects_prestart_or_runtime_path():
    app_control = _AppControl(True)
    fd_work = _FDWork()
    coordinator = PostPrivacyStartupCoordinator(
        app_control, participants=(fd_work,), privacy_authorized_reader=lambda: True
    )

    first = coordinator.start_if_authorized(pre_start=True)
    second = coordinator.start_if_authorized(pre_start=False)

    assert first["ok"] is True and second["ok"] is True
    assert app_control.calls == 1
    assert fd_work.authorizations == [True]
    assert fd_work.prepare_calls == [("prestart", False)]


def test_accepted_privacy_authorizes_fd_work_even_if_collector_start_fails():
    app_control = _AppControl(False)
    fd_work = _FDWork()
    coordinator = PostPrivacyStartupCoordinator(
        app_control, participants=(fd_work,), privacy_authorized_reader=lambda: True
    )

    result = coordinator.accept_privacy_notice_and_start()
    repeated = coordinator.accept_privacy_notice_and_start()

    assert result["ok"] is False and result["accepted"] is True
    assert repeated == result
    assert app_control.calls == 1
    assert fd_work.authorizations == [True]
    assert fd_work.prepare_calls == [("runtime", False)]
