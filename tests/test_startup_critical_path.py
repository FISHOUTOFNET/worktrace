from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.runtime.post_privacy_startup import PostPrivacyStartupCoordinator


pytestmark = [pytest.mark.unit, pytest.mark.integration, pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[1]


class _AppControl:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.start_calls = 0

    def start_collection_after_privacy_gate(self):
        self.start_calls += 1
        return {"ok": self.ok, "degraded": False}


class _Participant:
    def __init__(self) -> None:
        self.authorizations: list[bool] = []
        self.prepare_calls: list[bool] = []

    def set_privacy_authorized(self, authorized: bool) -> None:
        self.authorizations.append(bool(authorized))

    def prepare_after_privacy(self, *, pre_start: bool) -> None:
        self.prepare_calls.append(bool(pre_start))


def test_pre_webview_prepare_never_starts_collector_or_workers():
    app_control = _AppControl()
    participant = _Participant()
    coordinator = PostPrivacyStartupCoordinator(
        app_control,
        participants=(participant,),
        privacy_authorized_reader=lambda: True,
    )

    result = coordinator.prepare_before_webview_start()

    assert result == {
        "ok": True,
        "authorized": True,
        "prepared": True,
        "error": None,
    }
    assert app_control.start_calls == 0
    assert participant.authorizations == [True]
    assert participant.prepare_calls == [True]


def test_runtime_start_after_preparation_is_idempotent_and_does_not_reprepare():
    app_control = _AppControl()
    participant = _Participant()
    coordinator = PostPrivacyStartupCoordinator(
        app_control,
        participants=(participant,),
        privacy_authorized_reader=lambda: True,
    )

    coordinator.prepare_before_webview_start()
    first = coordinator.start_if_authorized(pre_start=False)
    second = coordinator.start_if_authorized(pre_start=False)

    assert first == second == {"ok": True, "degraded": False}
    assert app_control.start_calls == 1
    assert participant.prepare_calls == [True]


def test_unaccepted_privacy_preparation_remains_fail_closed_without_runtime_start():
    app_control = _AppControl()
    participant = _Participant()
    coordinator = PostPrivacyStartupCoordinator(
        app_control,
        participants=(participant,),
        privacy_authorized_reader=lambda: False,
    )

    result = coordinator.prepare_before_webview_start()

    assert result["ok"] is False
    assert result["authorized"] is False
    assert app_control.start_calls == 0
    assert participant.authorizations == [False]
    assert participant.prepare_calls == []


def test_shipping_entry_starts_runtime_from_renderer_callback_not_before_window_creation():
    source = (REPO_ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")

    prepare_index = source.index("prepare_before_webview_start")
    create_window_index = source.index("window = webview.create_window")
    renderer_callback_index = source.index("def handle_webview_initialized")
    deferred_start_index = source.index("app_control.start_if_authorized(pre_start=False)")
    webview_start_index = source.index("webview.start(")

    assert prepare_index < create_window_index
    assert create_window_index < renderer_callback_index < deferred_start_index
    assert deferred_start_index < webview_start_index
    assert "startup stage=main_window_created" in source
    assert "startup stage=renderer_initialized" in source
    assert "startup stage=runtime_ready" in source
