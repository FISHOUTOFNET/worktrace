from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from worktrace.api.app_api import ApplicationControlService
from worktrace.desktop.shell import DesktopShellController


class FakeRuntime:
    def __init__(self) -> None:
        self.running = True
        self.collector_control = SimpleNamespace(
            hold_state=SimpleNamespace(value="operational")
        )

    def is_collection_running_for_maintenance(self) -> bool:
        return self.running


class FakeMaintenance:
    def __init__(self) -> None:
        self.active = False
        self.blocked = False

    @property
    def blocked_reason(self):
        return "blocked" if self.blocked else None

    def operation_active(self) -> bool:
        return self.active

    def recovery_blocked(self) -> bool:
        return self.blocked

    @contextmanager
    def external_runtime_mutation_guard(self):
        yield


class FakeWindow:
    def destroy(self) -> None:
        return None


class FakeTray:
    def __init__(self) -> None:
        self.icon_states: list[bool] = []
        self.stop_calls = 0

    def start(self) -> bool:
        return True

    def stop(self) -> None:
        self.stop_calls += 1

    def show_background_notice(self) -> None:
        return None

    def set_collection_active(self, active: bool) -> None:
        self.icon_states.append(bool(active))


class FakeWindowIcons:
    def __init__(self) -> None:
        self.icon_states: list[bool] = []
        self.refresh_calls = 0
        self.stop_calls = 0

    def set_collection_active(self, active: bool) -> None:
        self.icon_states.append(bool(active))

    def refresh(self) -> None:
        self.refresh_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


def test_collection_active_requires_runtime_privacy_and_no_pause_or_maintenance(
    monkeypatch,
) -> None:
    runtime = FakeRuntime()
    maintenance = FakeMaintenance()
    service = ApplicationControlService(runtime, maintenance)
    privacy_allowed = {"value": True}
    paused = {"value": False}

    monkeypatch.setattr(
        "worktrace.api.app_api.privacy_gate_service.is_sensitive_runtime_allowed",
        lambda: privacy_allowed["value"],
    )
    monkeypatch.setattr(
        "worktrace.api.app_api.settings_api.is_user_paused",
        lambda: paused["value"],
    )

    assert service.is_collection_active() is True

    paused["value"] = True
    assert service.is_collection_active() is False
    paused["value"] = False

    privacy_allowed["value"] = False
    assert service.is_collection_active() is False
    privacy_allowed["value"] = True

    maintenance.active = True
    assert service.is_collection_active() is False
    maintenance.active = False

    maintenance.blocked = True
    assert service.is_collection_active() is False
    maintenance.blocked = False

    runtime.running = False
    assert service.is_collection_active() is False
    runtime.running = True

    runtime.collector_control.hold_state.value = "held"
    assert service.is_collection_active() is False


def test_desktop_shell_projects_collection_state_to_both_icon_surfaces() -> None:
    state = {"active": True}
    tray = FakeTray()
    window_icons = FakeWindowIcons()
    shell = DesktopShellController(
        window=FakeWindow(),
        tray=tray,
        window_icons=window_icons,
        collection_active_provider=lambda: state["active"],
        collection_icon_refresh_seconds=60.0,
    )

    try:
        assert shell.start() is True
        assert tray.icon_states == [True]
        assert window_icons.icon_states == [True]

        state["active"] = False
        shell._refresh_collection_icon_state(force=False)
        assert tray.icon_states == [True, False]
        assert window_icons.icon_states == [True, False]
    finally:
        shell.stop()


def test_desktop_shell_icon_provider_failure_fails_closed() -> None:
    tray = FakeTray()
    window_icons = FakeWindowIcons()

    def fail() -> bool:
        raise RuntimeError("state unavailable")

    shell = DesktopShellController(
        window=FakeWindow(),
        tray=tray,
        window_icons=window_icons,
        collection_active_provider=fail,
        collection_icon_refresh_seconds=60.0,
    )

    try:
        assert shell.start() is True
        assert tray.icon_states == [False]
        assert window_icons.icon_states == [False]
    finally:
        shell.stop()
