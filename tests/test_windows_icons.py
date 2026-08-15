from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from worktrace.desktop.windows_icons import WindowsWindowIconHost, load_icon_variant


def _fake_win32_modules():
    calls: dict[str, list] = {
        "load": [],
        "post": [],
        "destroy": [],
    }
    next_handle = {"value": 100}
    con = SimpleNamespace(
        LR_LOADFROMFILE=0x0010,
        LR_DEFAULTSIZE=0x0040,
        LR_MONOCHROME=0x0001,
        IMAGE_ICON=1,
        WM_SETICON=0x0080,
        ICON_BIG=1,
        ICON_SMALL=0,
        SM_CXICON=11,
        SM_CYICON=12,
        SM_CXSMICON=49,
        SM_CYSMICON=50,
    )

    def load_image(_instance, path, image_type, width, height, flags):
        handle = next_handle["value"]
        next_handle["value"] += 1
        calls["load"].append((path, image_type, width, height, flags, handle))
        return handle

    gui = SimpleNamespace(
        LoadImage=load_image,
        FindWindow=lambda _class, title: 321 if title == "WorkTrace" else 0,
        PostMessage=lambda hwnd, msg, kind, handle: calls["post"].append(
            (hwnd, msg, kind, handle)
        ),
        DestroyIcon=lambda handle: calls["destroy"].append(handle),
    )

    metrics = {11: 32, 12: 32, 49: 16, 50: 16}
    api = SimpleNamespace(GetSystemMetrics=lambda metric: metrics[metric])
    return calls, con, gui, api


def test_inactive_icon_variant_prefers_packaged_paused_resource(tmp_path) -> None:
    active_path = tmp_path / "app.ico"
    paused_path = tmp_path / "app-paused.ico"
    active_path.touch()
    paused_path.touch()
    calls, con, gui, _api = _fake_win32_modules()

    with patch.dict(sys.modules, {"win32con": con, "win32gui": gui}):
        load_icon_variant(active_path, active=True)
        load_icon_variant(active_path, active=False)

    assert calls["load"][0][0] == str(active_path)
    assert calls["load"][1][0] == str(paused_path)
    active_flags = calls["load"][0][4]
    inactive_flags = calls["load"][1][4]
    assert active_flags & con.LR_LOADFROMFILE
    assert active_flags & con.LR_DEFAULTSIZE
    assert not active_flags & con.LR_MONOCHROME
    assert not inactive_flags & con.LR_MONOCHROME


def test_inactive_icon_variant_keeps_source_run_monochrome_fallback(tmp_path) -> None:
    active_path = tmp_path / "app.ico"
    active_path.touch()
    calls, con, gui, _api = _fake_win32_modules()

    with patch.dict(sys.modules, {"win32con": con, "win32gui": gui}):
        load_icon_variant(active_path, active=False)

    assert calls["load"][0][0] == str(active_path)
    assert calls["load"][0][4] & con.LR_MONOCHROME


def test_window_icon_host_updates_large_and_small_taskbar_icons_nonblocking(
    tmp_path,
) -> None:
    active_path = tmp_path / "app.ico"
    paused_path = tmp_path / "app-paused.ico"
    active_path.touch()
    paused_path.touch()
    calls, con, gui, api = _fake_win32_modules()

    with patch.dict(
        sys.modules,
        {"win32con": con, "win32gui": gui, "win32api": api},
    ):
        host = WindowsWindowIconHost(
            window_title="WorkTrace",
            icon_path=active_path,
        )
        host.set_collection_active(False)
        host.set_collection_active(True)
        host.stop()

    assert len(calls["load"]) == 4
    assert [Path(call[0]).name for call in calls["load"][:2]] == [
        "app-paused.ico",
        "app-paused.ico",
    ]
    assert [Path(call[0]).name for call in calls["load"][2:]] == [
        "app.ico",
        "app.ico",
    ]
    assert all(not call[4] & con.LR_MONOCHROME for call in calls["load"])

    assert [call[2] for call in calls["post"]] == [
        con.ICON_BIG,
        con.ICON_SMALL,
        con.ICON_BIG,
        con.ICON_SMALL,
    ]
    assert sorted(calls["destroy"]) == [100, 101, 102, 103]
