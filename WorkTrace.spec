# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)

datas = [
    (str(root / 'worktrace' / 'schema.sql'), 'worktrace'),
    (str(root / 'worktrace' / 'platforms' / 'open_files_helper.py'), 'worktrace/platforms'),
    (str(root / 'worktrace' / 'webview_ui' / 'index.html'), 'worktrace/webview_ui'),
    (str(root / 'worktrace' / 'webview_ui' / 'app.js'), 'worktrace/webview_ui'),
    (str(root / 'worktrace' / 'webview_ui' / 'styles.css'), 'worktrace/webview_ui'),
]
binaries = []
hiddenimports = ['win32timezone']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# pywebview (optional WebView spike). collect_all('webview') is a no-op if
# pywebview is not installed; the Tkinter-only default entry point does not
# import webview, so a missing pywebview does not break the default build.
_wv_ret = collect_all('webview')
datas += _wv_ret[0]; binaries += _wv_ret[1]; hiddenimports += _wv_ret[2]


a = Analysis(
    [str(root / 'scripts' / 'pyinstaller_entry.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WorkTrace',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
