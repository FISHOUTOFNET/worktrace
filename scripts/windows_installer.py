from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def payload_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    packaged = base / "payload" / "WorkTrace.exe"
    if packaged.exists():
        return packaged
    local = Path(__file__).resolve().parent / "WorkTrace.exe"
    if local.exists():
        return local
    raise FileNotFoundError("WorkTrace.exe payload was not found.")


def default_install_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        local_appdata = str(Path.home() / "AppData" / "Local")
    return Path(local_appdata) / "Programs" / "WorkTrace"


def default_start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_shortcut(shortcut_path: Path, target_exe: Path) -> None:
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$ShortcutPath = {powershell_literal(str(shortcut_path))}",
            f"$TargetPath = {powershell_literal(str(target_exe))}",
            f"$WorkingDirectory = {powershell_literal(str(target_exe.parent))}",
            "$Shell = New-Object -ComObject WScript.Shell",
            "$Shortcut = $Shell.CreateShortcut($ShortcutPath)",
            "$Shortcut.TargetPath = $TargetPath",
            "$Shortcut.WorkingDirectory = $WorkingDirectory",
            "$Shortcut.IconLocation = $TargetPath",
            "$Shortcut.Description = 'WorkTrace'",
            "$Shortcut.Save()",
        ]
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install WorkTrace for the current Windows user.")
    parser.add_argument("--install-dir", default=os.environ.get("WORKTRACE_INSTALL_ROOT"))
    parser.add_argument("--start-menu-dir", default=os.environ.get("WORKTRACE_START_MENU_DIR"))
    parser.add_argument("--no-shortcut", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = payload_path()
    install_dir = Path(args.install_dir) if args.install_dir else default_install_dir()
    install_dir.mkdir(parents=True, exist_ok=True)

    target = install_dir / "WorkTrace.exe"
    shutil.copy2(source, target)

    shortcut_path: Path | None = None
    if not args.no_shortcut:
        start_menu_dir = Path(args.start_menu_dir) if args.start_menu_dir else default_start_menu_dir()
        start_menu_dir.mkdir(parents=True, exist_ok=True)
        shortcut_path = start_menu_dir / "WorkTrace.lnk"
        create_shortcut(shortcut_path, target)

    if not args.quiet:
        print(f"Installed WorkTrace to {target}")
        if shortcut_path:
            print(f"Created shortcut at {shortcut_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"WorkTrace installer failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
