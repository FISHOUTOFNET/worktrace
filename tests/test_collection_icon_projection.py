from __future__ import annotations

from worktrace.desktop.collection_icon_projection import CollectionIconProjectionHost


class _Tray:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.available = False
        self.active_values: list[bool] = []

    def start(self) -> bool:
        self.start_calls += 1
        self.available = True
        return True

    def stop(self) -> None:
        self.stop_calls += 1
        self.available = False

    def can_restore_window(self) -> bool:
        return self.available

    def set_collection_active(self, active: bool) -> None:
        self.active_values.append(bool(active))

    def show_background_notice(self) -> None:
        pass


class _WindowIcons:
    def __init__(self) -> None:
        self.active_values: list[bool] = []

    def set_collection_active(self, active: bool) -> None:
        self.active_values.append(bool(active))


def test_projection_updates_headless_tray_when_collection_becomes_live() -> None:
    state = {"active": False}
    tray = _Tray()
    host = CollectionIconProjectionHost(
        tray=tray,
        collection_active_provider=lambda: state["active"],
    )

    try:
        assert host.start() is True
        assert tray.active_values[-1] is False

        state["active"] = True
        host._refresh(force=False)

        assert tray.active_values[-1] is True
        assert tray.start_calls == 1
    finally:
        host.stop()


def test_window_icon_attachment_reuses_current_projection_without_second_owner() -> None:
    state = {"active": True}
    tray = _Tray()
    window_icons = _WindowIcons()
    host = CollectionIconProjectionHost(
        tray=tray,
        collection_active_provider=lambda: state["active"],
    )

    try:
        assert host.start() is True
        host.attach_window_icons(window_icons)
        assert window_icons.active_values == [True]

        state["active"] = False
        host._refresh(force=False)
        assert tray.active_values[-1] is False
        assert window_icons.active_values[-1] is False
    finally:
        host.stop()


def test_start_is_idempotent_while_tray_is_restorable() -> None:
    tray = _Tray()
    host = CollectionIconProjectionHost(
        tray=tray,
        collection_active_provider=lambda: True,
    )

    try:
        assert host.start() is True
        assert host.start() is True
        assert tray.start_calls == 1
    finally:
        host.stop()


def test_provider_failure_fails_closed_and_recovers() -> None:
    calls = {"fail": True}
    tray = _Tray()

    def provider() -> bool:
        if calls["fail"]:
            raise RuntimeError("boom")
        return True

    host = CollectionIconProjectionHost(
        tray=tray,
        collection_active_provider=provider,
    )

    try:
        assert host.start() is True
        assert tray.active_values[-1] is False

        calls["fail"] = False
        host._refresh(force=False)
        assert tray.active_values[-1] is True
    finally:
        host.stop()
